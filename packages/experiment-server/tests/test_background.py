"""Real Windows/Linux background handshake and cooperative exact-worker stop."""
import copy,time
from pathlib import Path
from experiment_server.storage import init,read
from experiment_server.config import read_config
from experiment_server.manager import register,start,status,stop
from experiment_server.recovery import check

def test_actual_background_and_cooperative_stop(tmp_path):
    root=tmp_path/'work';init(root,8)
    c=read_config(Path(__file__).parents[1]/'experiment_server/examples/two-body.json')
    c['integration']['interval_yr']=.001;c['integration']['checkpoint_yr']=.1
    register(root,'realworker',c)
    handles=start(root,['realworker'],10000)
    assert len(handles)==1 and not handles[0]['pending']
    deadline=time.monotonic()+20
    while not (root/'runs/realworker/status.json').exists() and time.monotonic()<deadline:time.sleep(.1)
    assert status(root)['cases'][0]['alive']
    stop(root,'realworker')
    deadline=time.monotonic()+30
    while status(root)['cases'][0]['alive'] and time.monotonic()<deadline:time.sleep(.2)
    result=status(root)['cases'][0]
    assert result['alive'] is False and result['state']=='stopped_explicitly'
    proof=check(root,'realworker');assert proof['actual_epoch_yr']<10000 and proof['particles']==2
