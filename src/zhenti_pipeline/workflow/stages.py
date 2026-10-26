"""工作流阶段层（S4）：确定性核心的阶段编排、续跑与审批门。

设计（方案 §5.1/§5.3、§1 不依赖专有 DSL）：
- 阶段图来自 v2 工作流（zhenti-pipeline-v2.dwf.ts 的确定性骨架）；agent/人工阶段
  （转录、复核、发送、批准）**不在**本层执行——本层只做确定性执行与资格判定，
  在需要人/agent 的阶段返回 pending 并写 run_state 的 pausePoint/nextStage；
- 状态与审批复用 storage/run_state + storage/approvals（合同由 S2 测试锁定）；
- 核内工具（run_state/approvals）经 `python -m` 调用本包模块，发布包内自足；
  成书工具链执行脚本（merge/gate/build/publish/勘误）属发布边界之外的内部工具层：
  环境变量显式指定 → 仓库开发布局回退 → 都没有则阶段返回 pending 并说明
  （0.1.0-rc.1 公开包不含工具链，见 docs/release/RELEASE-CHECKLIST.md）；
- 一切资料路径相对显式 workspace；不回落历史科目。
"""

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from zhenti_pipeline.domain import check_papers

# 确定性阶段图（顺序执行）。agent/人工：transcribe/review/approve 类阶段由 skill 层推进。
STAGE_GRAPH = [
    # (stage, 是否本层可执行, 说明)
    ("index", True, "原料/卷清单就绪检查：papers/<subject> 存在、textbook/meta 完整"),
    ("verify", True, "run_state verify（参数回声+输入指纹+章树哈希漂移停机）"),
    ("check", True, "check_papers 只读交接检查（missing/双归属/图片）"),
    ("gate", True, "publication_gate 出版权威门禁（需渲染器）"),
    ("merge-preview", True, "merge_papers 预览 → 合并指纹（待批准）"),
    ("merge-apply", "approval", "凭据 type=merge 批准后正式写 bank（外发/写库分界）"),
    ("errata", "approval", "勘误表 apply（凭据 type=errata-write；表由外审闭环产出）"),
    ("build", True, "build_book 隔离构建（真实 TeX；无工具链时 pending）"),
    ("publish", "approval", "publish_book 原子落位（凭据 type=publish；默认 dry-run）"),
]
AGENT_STAGES = {"transcribe", "review", "preface", "dispatch-send", "external-review"}


@dataclass
class StageResult:
    stage: str
    status: str  # ok | blocked | pending | invalid-input
    detail: str = ""
    data: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "stage": self.stage,
            "status": self.status,
            "detail": self.detail,
            "data": self.data,
        }


def _dev_tool(*parts: str) -> Path | None:
    """仓库开发布局回退：sources/ 快照存在时返回工具路径，否则 None（发布包无快照）。"""
    p = Path(__file__).resolve().parents[3]
    for part in ("sources", *parts):
        p = p / part
    return p if p.is_file() else None


def _resolve_tool(env_value: str | None, *dev_parts: str) -> Path | None:
    if env_value:
        return Path(env_value)
    return _dev_tool(*dev_parts)


TOOLS_PENDING = (
    "成书工具链不在本发布包内（0.1.0-rc.1 只含核心）。"
    "设 ZHENTI_MERGE_PAPERS / ZHENTI_PUBLICATION_GATE / ZHENTI_BUILD_BOOK / "
    "ZHENTI_PUBLISH_BOOK / ZHENTI_APPLY_ERRATA 指向工具目录，或在开发仓库内使用。"
)


class WorkflowRunner:
    """显式 workspace 的阶段编排器。所有子进程 cwd=workspace（执行器现有合同）。"""

    def __init__(
        self,
        workspace: Path,
        subject: str,
        batch_id: str,
        run_id: str | None = None,
        env: dict | None = None,
    ):
        self.workspace = Path(workspace).resolve()
        self.subject = subject
        self.batch_id = batch_id
        self.run_id = run_id or f"{subject}-{batch_id}"
        # runs 根固定在本 workspace 下并注入子进程环境——保证状态落点一致；
        # 并把包 src/ 前置到 PYTHONPATH，保证未安装（开发布局）时 `python -m` 可用。
        runs_root = Path(os.environ.get("ZHENTI_RUNS_DIR") or (self.workspace / "runs"))
        self.run_dir = runs_root / self.run_id
        pkg_src = str(Path(__file__).resolve().parents[2])
        py_path = os.pathsep.join([pkg_src, os.environ.get("PYTHONPATH", "")]).rstrip(os.pathsep)
        self.env = {
            **os.environ,
            "PYTHONUTF8": "1",
            "PYTHONPATH": py_path,
            "ZHENTI_RUNS_DIR": str(runs_root),
            **(env or {}),
        }

    # ── 基础 ──
    def _py(self, *cmd, timeout=900):
        return subprocess.run(
            [sys.executable, *[str(c) for c in cmd]],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(self.workspace),
            env=self.env,
            timeout=timeout,
        )

    def _py_module(self, module: str, *args, timeout=900):
        return self._py("-m", module, *args, timeout=timeout)

    def _state_path(self) -> Path:
        return self.run_dir / "state.json"

    def load_state(self) -> dict | None:
        p = self._state_path()
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None

    def _order_index(self, name: str) -> int:
        order = [s[0] for s in STAGE_GRAPH]
        if name not in order:
            raise KeyError(f"未知阶段 {name!r}（可选：{order}）")
        return order.index(name)

    # ── plan / status（只读） ──
    def plan(self) -> dict:
        st = self.load_state()
        stages = []
        for name, executable, note in STAGE_GRAPH:
            stages.append(
                {
                    "stage": name,
                    "executableHere": executable is True,
                    "kind": {True: "deterministic", "approval": "approval-gated"}[executable],
                    "note": note,
                }
            )
        for name in sorted(AGENT_STAGES):
            stages.append(
                {
                    "stage": name,
                    "executableHere": False,
                    "kind": "agent/human",
                    "note": "由 skill 会话推进，不由本层执行",
                }
            )
        return {
            "workspace": str(self.workspace),
            "subject": self.subject,
            "batchId": self.batch_id,
            "runId": self.run_id,
            "initialized": st is not None,
            "pausePoint": (st or {}).get("pausePoint"),
            "nextStage": (st or {}).get("nextStage"),
            "revision": (st or {}).get("revision"),
            "stages": stages,
        }

    def status(self) -> dict:
        st = self.load_state()
        if st is None:
            return {"initialized": False, "runDir": str(self.run_dir)}
        return {
            "initialized": True,
            "runDir": str(self.run_dir),
            **{
                k: st.get(k)
                for k in (
                    "runId",
                    "revision",
                    "pausePoint",
                    "nextStage",
                    "papers",
                    "approvalIds",
                    "argsEcho",
                )
            },
        }

    # ── 执行 ──
    def run_stage(self, name: str, approve: str | None = None) -> StageResult:
        kind = dict((s[0], s[1]) for s in STAGE_GRAPH).get(name)
        if kind is None:
            if name in AGENT_STAGES:
                return StageResult(
                    name, "pending", "agent/人工阶段：由 skill 会话推进（本层不执行）"
                )
            return StageResult(name, "invalid-input", f"未知阶段 {name!r}")
        if kind == "approval" and not approve:
            return StageResult(
                name,
                "pending",
                f"{name} 是审批门阶段：需凭据 verify 输出作为 --approve（先 approvals record/verify）",
            )
        handler = getattr(self, f"_stage_{name.replace('-', '_')}", None)
        if handler is None:
            return StageResult(name, "invalid-input", "本层未实现该阶段执行器")
        result = handler(approve)
        if result.status == "ok":
            self._record_progress(name)
        return result

    def _record_progress(self, name: str) -> None:
        """成功后把 pausePoint/nextStage 写入 run_state（resume 的依据）。"""
        order = [s[0] for s in STAGE_GRAPH]
        nxt = order[min(self._order_index(name) + 1, len(order) - 1)]
        self._py_module(
            "zhenti_pipeline.storage.run_state",
            "set-point",
            "--run-dir",
            self.run_dir,
            "--pause-point",
            name,
            "--next-stage",
            nxt,
        )

    def resume(self, approve: str | None = None) -> StageResult:
        """按 run_state 的 nextStage 续跑（中断后的标准入口）。"""
        st = self.load_state()
        if st is None:
            return StageResult("resume", "invalid-input", "run 未初始化（先 run init）")
        nxt = st.get("nextStage")
        if not nxt:
            return StageResult("resume", "pending", "状态未记录下一步")
        r = self.run_stage(nxt, approve=approve)
        r.detail = f"resume→{nxt}: {r.detail}"
        return r

    # ── 各阶段 ──
    def _stage_index(self, approve=None) -> StageResult:
        papers = self.workspace / "papers" / self.subject
        missing = [x for x in ("textbook.json", "meta.json") if not (papers / x).is_file()]
        if missing:
            return StageResult("index", "blocked", f"papers/{self.subject} 缺 {missing}")
        n_papers = len(
            [p for p in papers.glob("*.json") if p.name not in ("textbook.json", "meta.json")]
        )
        if n_papers == 0:
            return StageResult("index", "blocked", "无卷级 JSON（先转录交接）")
        init = self._py_module(
            "zhenti_pipeline.storage.run_state",
            "init",
            "--subject",
            self.subject,
            "--batch-id",
            self.batch_id,
            "--input-dir",
            "input",
            "--config-path",
            "config.json",
        )
        if init.returncode != 0 and "reused" not in init.stdout:
            return StageResult(
                "index",
                "blocked",
                f"run_state init 未过：{init.stderr[-300:]}",
                data={"note": "input/ config.json 需存在（hash_inputs fail-closed）"},
            )
        return StageResult("index", "ok", f"卷清单就绪（{n_papers} 卷）", data={"papers": n_papers})

    def _stage_verify(self, approve=None) -> StageResult:
        r = self._py_module(
            "zhenti_pipeline.storage.run_state",
            "verify",
            "--subject",
            self.subject,
            "--batch-id",
            self.batch_id,
            "--input-dir",
            "input",
            "--config-path",
            "config.json",
        )
        if r.returncode != 0:
            return StageResult("verify", "blocked", f"漂移或未初始化：{r.stderr[-400:]}")
        return StageResult("verify", "ok", "参数/输入/章树无漂移", data=json.loads(r.stdout))

    def _stage_check(self, approve=None) -> StageResult:
        papers = self.workspace / "papers" / self.subject
        result = check_papers.audit(papers)
        if not result["ok"]:
            return StageResult(
                "check",
                "blocked",
                "check_papers 未过（原题保留可定位）",
                data={"errors": result["errors"][:10], "stats": result["stats"]},
            )
        return StageResult(
            "check",
            "ok",
            "交接检查通过",
            data={"stats": result["stats"], "warnings": result["warnings"]},
        )

    def _stage_gate(self, approve=None) -> StageResult:
        gate = _resolve_tool(
            self.env.get("ZHENTI_PUBLICATION_GATE"),
            "skills/exam-compilation/scripts/publication_gate.py",
        )
        renderer = _resolve_tool(
            self.env.get("ZHENTI_RENDERER"), "exam-compilation-project/tools/make_book.py"
        )
        bank = (
            self.workspace / "exam-compilation/exam-compilation/bank-data" / f"{self.subject}.json"
        )
        if not bank.is_file():
            return StageResult("gate", "pending", "bank 未生成（先 merge-apply）")
        if gate is None or renderer is None:
            return StageResult("gate", "pending", TOOLS_PENDING)
        r = self._py(
            gate,
            "--bank",
            bank,
            "--renderer",
            renderer,
            "--subject",
            self.subject,
            "--source-images",
            f"papers/{self.subject}/images",
        )
        if r.returncode != 0:
            return StageResult(
                "gate", "blocked", f"publication_gate 未过：{(r.stdout or r.stderr)[-400:]}"
            )
        return StageResult(
            "gate", "ok", "出版门禁通过", data=json.loads(r.stdout) if r.stdout.strip() else {}
        )

    def _stage_merge_preview(self, approve=None) -> StageResult:
        merge = _resolve_tool(
            self.env.get("ZHENTI_MERGE_PAPERS"), "skills/exam-compilation/scripts/merge_papers.py"
        )
        if merge is None:
            return StageResult("merge-preview", "pending", TOOLS_PENDING)
        report = self.run_dir / "merge-preview.json"
        self.run_dir.mkdir(parents=True, exist_ok=True)
        r = self._py(
            merge,
            "--papers-root",
            "papers",
            "--bank-dir",
            "exam-compilation/exam-compilation/bank-data",
            "--subject",
            self.subject,
            "--report",
            report,
        )
        if r.returncode != 0:
            return StageResult(
                "merge-preview", "blocked", f"merge 预览失败：{(r.stdout or r.stderr)[-400:]}"
            )
        pv = json.loads(report.read_text(encoding="utf-8"))
        return StageResult(
            "merge-preview",
            "ok" if not pv.get("conflicts") else "blocked",
            f"指纹 {pv.get('fingerprint', '')[:16]}…（待用户批准后 record+merge-apply）",
            data={
                k: pv.get(k)
                for k in ("fingerprint", "added", "unchanged", "conflicts", "retained_only")
            },
        )

    def _stage_merge_apply(self, approve: str) -> StageResult:
        merge = _resolve_tool(
            self.env.get("ZHENTI_MERGE_PAPERS"), "skills/exam-compilation/scripts/merge_papers.py"
        )
        if merge is None:
            return StageResult("merge-apply", "pending", TOOLS_PENDING)
        prev = self.run_dir / "merge-preview.json"
        if not prev.is_file():
            return StageResult("merge-apply", "pending", "先 merge-preview 取本次指纹")
        report = self.run_dir / "merge-apply.json"
        r = self._py(
            merge,
            "--papers-root",
            "papers",
            "--bank-dir",
            "exam-compilation/exam-compilation/bank-data",
            "--subject",
            self.subject,
            "--report",
            report,
            "--apply",
            "--approve",
            approve or "",
        )
        if r.returncode != 0:
            return StageResult(
                "merge-apply",
                "blocked",
                f"merge apply 未过（凭据/指纹/漂移）：{(r.stdout or r.stderr)[-400:]}",
            )
        return StageResult(
            "merge-apply", "ok", "bank 已更新", data=json.loads(report.read_text(encoding="utf-8"))
        )

    def _stage_errata(self, approve: str) -> StageResult:
        apply_errata = _resolve_tool(
            self.env.get("ZHENTI_APPLY_ERRATA"),
            "workflow/optimization/v2/pipeline/apply_errata_v2.py",
        )
        if apply_errata is None:
            return StageResult("errata", "pending", TOOLS_PENDING)
        table = self.env.get("ZHENTI_ERRATA_TABLE", "")
        if not table or not Path(table).is_file():
            return StageResult(
                "errata", "pending", "未提供勘误表（设 ZHENTI_ERRATA_TABLE；外审闭环产出）"
            )
        r = self._py(
            apply_errata,
            "apply",
            "--table",
            table,
            "--subject",
            self.subject,
            "--approve",
            approve or "",
        )
        if r.returncode != 0:
            return StageResult(
                "errata", "blocked", f"勘误 apply 未过：{(r.stdout or r.stderr)[-400:]}"
            )
        return StageResult("errata", "ok", "双侧直改事务已提交", data=json.loads(r.stdout))

    def _stage_build(self, approve=None) -> StageResult:
        import shutil

        if not shutil.which("xelatex") and not Path(self.env.get("TEXBIN", "")).is_file():
            return StageResult(
                "build", "pending", "本机无 XeLaTeX：渲染层需真实工具链（CI 渲染 job 待许可核清）"
            )
        build_book = _resolve_tool(
            self.env.get("ZHENTI_BUILD_BOOK"),
            "workflow/optimization/v2/build-publish/build_book.py",
        )
        renderer = _resolve_tool(
            self.env.get("ZHENTI_RENDERER"), "exam-compilation-project/tools/make_book.py"
        )
        if build_book is None or renderer is None:
            return StageResult("build", "pending", TOOLS_PENDING)
        bank = (
            self.workspace / "exam-compilation/exam-compilation/bank-data" / f"{self.subject}.json"
        )
        r = self._py(
            build_book,
            "--bank",
            bank,
            "--subject",
            self.subject,
            "--run-dir",
            self.run_dir,
            "--renderer",
            renderer,
        )
        if r.returncode != 0:
            return StageResult("build", "blocked", f"构建未过：{(r.stderr or r.stdout)[-400:]}")
        return StageResult("build", "ok", "构建成功", data=json.loads(r.stdout))

    def _stage_publish(self, approve: str) -> StageResult:
        publish = _resolve_tool(
            self.env.get("ZHENTI_PUBLISH_BOOK"),
            "workflow/optimization/v2/build-publish/publish_book.py",
        )
        if publish is None:
            return StageResult("publish", "pending", TOOLS_PENDING)
        pdf = self.env.get("ZHENTI_PUBLISH_PDF", "")
        if not pdf or not Path(pdf).is_file():
            return StageResult("publish", "pending", "未提供隔离构建 PDF（设 ZHENTI_PUBLISH_PDF）")
        r = self._py(
            publish,
            "--pdf",
            pdf,
            "--subject",
            self.subject,
            "--target-dir",
            "exam-compilation/exam-compilation/book",
            *(["--apply", "--approve", approve] if approve else []),
        )
        if r.returncode != 0:
            return StageResult("publish", "blocked", f"落位未过：{(r.stdout or r.stderr)[-400:]}")
        return StageResult("publish", "ok", "已落位（或 dry-run）", data=json.loads(r.stdout))
