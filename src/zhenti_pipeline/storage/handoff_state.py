#!/usr/bin/env python3
"""跨会话接力：状态快照 + 输入指纹 + 所有者锁；无自动抢占。"""
import argparse, datetime, hashlib, json, pathlib, sys
from zhenti_pipeline.storage.safe_io import safe_replace, sha256
STAGES=('queued','working','blocked','review','approved','done')

def snapshot(inputs):
    return {str(pathlib.Path(p).resolve()):sha256(p) for p in inputs}

def update(path, *, owner, state, inputs, note='', expected_revision=None):
    path=pathlib.Path(path).resolve(); prior=json.loads(path.read_text(encoding='utf-8')) if path.exists() else None
    if state not in STAGES:raise ValueError('未知状态')
    if prior and expected_revision is None:raise ValueError('已有任务必须带 --revision 防止旧会话覆盖')
    if prior and prior['revision']!=expected_revision:raise ValueError('接力版本过期')
    if prior and prior['owner']!=owner and prior['state']=='working':raise ValueError('任务仍归原 owner；必须先 handoff 为 review/blocked')
    hashes=snapshot(inputs)
    if prior and prior['inputs']!=hashes:raise ValueError('输入发生变化，须建立新的审批/任务记录')
    record={'revision':(prior['revision']+1 if prior else 1),'owner':owner,'state':state,'inputs':hashes,
            'note':note,'updated_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()}
    safe_replace(path,(json.dumps(record,ensure_ascii=False,indent=2)+'\n').encode(),owner=owner,
                 expected_sha256=sha256(path) if prior else None,backup=bool(prior))
    return record

def main():
    p=argparse.ArgumentParser();p.add_argument('--state-file',required=True);p.add_argument('--owner',required=True)
    p.add_argument('--status',required=True,choices=STAGES);p.add_argument('--input',action='append',required=True)
    p.add_argument('--revision',type=int);p.add_argument('--note',default='')
    a=p.parse_args()
    try:print(json.dumps(update(a.state_file,owner=a.owner,state=a.status,inputs=a.input,note=a.note,expected_revision=a.revision),ensure_ascii=False,indent=2))
    except (OSError,ValueError,RuntimeError) as e:p.exit(2,'BLOCKED: '+str(e)+'\n')
if __name__=='__main__':main()
