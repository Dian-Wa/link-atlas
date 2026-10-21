import importlib.util
from pathlib import Path
from fastapi.testclient import TestClient

spec=importlib.util.spec_from_file_location('atlas_local_service_tests',Path(__file__).parents[1]/'server/service.py')
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
ORIGIN='https://dian-wa.github.io'


def test_public_origin_private_network_preflight():
    with TestClient(module.create_service(origins=[ORIGIN]),base_url='http://127.0.0.1:8787') as c:
        response=c.options('/fetch-api/fetch',headers={'Origin':ORIGIN,'Access-Control-Request-Method':'POST','Access-Control-Request-Headers':'content-type','Access-Control-Request-Private-Network':'true'})
        assert response.status_code==200
        assert response.headers['access-control-allow-origin']==ORIGIN
        assert response.headers.get('access-control-allow-private-network')=='true'
        rejected=c.options('/fetch-api/fetch',headers={'Origin':'https://evil.example','Access-Control-Request-Method':'POST','Access-Control-Request-Private-Network':'true'})
        assert rejected.status_code==400
        assert 'access-control-allow-private-network' not in rejected.headers


def test_local_service_host_control_and_health():
    stopped=[]
    app=module.create_service(origins=[ORIGIN],local_only=True,shutdown_token='test-control-token',shutdown_callback=lambda:stopped.append(True))
    with TestClient(app,base_url='http://127.0.0.1:8787') as c:
        value=c.get('/fetch-api/health').json()
        assert value['app']=='link-atlas-fetch' and value['mode']=='local' and value['storage']=='none'
        assert c.get('/fetch-api/health',headers={'Host':'evil.example'}).status_code==400
        assert c.post('/fetch-api/control/stop',headers={'Origin':'http://127.0.0.1:8787'}).status_code==403
        response=c.post('/fetch-api/control/stop',headers={'Origin':'http://127.0.0.1:8787','X-Atlas-Control':'test-control-token'})
        assert response.status_code==200 and stopped==[True]


def test_cloud_mode_has_no_control_endpoint():
    with TestClient(module.create_service(origins=[ORIGIN]),base_url='http://127.0.0.1:8787') as c:
        assert c.post('/fetch-api/control/stop',headers={'Origin':ORIGIN}).status_code in (404,405)
