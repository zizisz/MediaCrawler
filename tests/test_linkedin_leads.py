import asyncio

import pytest
from fastapi import HTTPException
from api.routers import ai
from api.services.linkedin import company_url, lead_fields


def test_company_url_and_empty_data():
    assert company_url('https://linkedin.com/company/acme/about/?trk=x') == 'https://www.linkedin.com/company/acme/'
    for url in ['http://linkedin.com/company/acme', 'https://linkedin.com.evil.test/company/acme',
                'https://user@linkedin.com/company/acme', 'https://linkedin.com/in/person',
                'https://linkedin.com/company/a/../../foo', 'https://localhost/company/acme']:
        with pytest.raises(ValueError):
            company_url(url)
    with pytest.raises(ValueError):
        lead_fields({'name': 'Unknown Company'}, 'https://linkedin.com/company/acme/')


def test_background_merge_one_company_and_logs(tmp_path, monkeypatch):
    monkeypatch.setattr(ai, 'LEADS_FILE', tmp_path / 'leads.json')
    monkeypatch.setattr(ai, 'AI_DIR', tmp_path)
    monkeypatch.setattr(ai, '_linkedin_task', None)
    monkeypatch.setattr(ai, '_linkedin_job', {'status': 'idle'})
    original = {'id': 'one', 'company_name': '原名称', 'company_info': '原抖音资料',
                'source_urls': 'https://douyin.com/old', 'source_platform': 'Douyin',
                'followed_up': True, 'patents': 'EP123', 'created_at': 'old'}
    other = {'id': 'two', 'company_name': '别家', 'company_info': '不应变更'}
    ai._write_leads([original, other])
    logs = []

    async def log(message, level='info'):
        logs.append((message, level))

    async def fetch(url):
        await asyncio.sleep(0)
        return {'name': 'New Name', 'industry': 'Plastics', 'website': 'https://example.test'}

    monkeypatch.setattr(ai, '_linkedin_log', log)
    monkeypatch.setattr(ai, 'fetch_company', fetch)

    async def run():
        request = ai.LinkedInRequest(url='https://www.linkedin.com/company/acme/')
        await ai.collect_linkedin('one', request)
        with pytest.raises(HTTPException) as error:
            await ai.collect_linkedin('two', request)
        assert error.value.status_code == 409
        await ai._linkedin_task

    asyncio.run(run())
    result, untouched = ai._read_leads()
    assert result['id'] == 'one' and result['company_name'] == '原名称'
    assert result['followed_up'] and result['patents'] == 'EP123'
    assert result['created_at'] == 'old' and untouched == other
    assert '原抖音资料' in result['company_info'] and 'Plastics' in result['company_info']
    assert result['source_platform'] == 'Douyin; LinkedIn'
    assert 'https://douyin.com/old' in result['source_urls']
    assert result['aliases'] == 'New Name'
    assert ai._linkedin_job['status'] == 'completed'
    assert len(logs) == 4 and logs[-1][1] == 'success'

    async def fail(url):
        raise ValueError('登录失效')

    monkeypatch.setattr(ai, 'fetch_company', fail)
    before = ai.LEADS_FILE.read_bytes()
    asyncio.run(ai._collect_linkedin('one', '原名称', 'https://www.linkedin.com/company/acme/'))
    assert ai.LEADS_FILE.read_bytes() == before
    assert ai._linkedin_job['status'] == 'error' and logs[-1][1] == 'error'
