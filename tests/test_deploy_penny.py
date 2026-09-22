from unittest.mock import patch

import pytest
from scripts import deploy_penny as deploy


@pytest.mark.parametrize('answers,reason', [
    ([' M watcher.py'], 'checkout_dirty'),
    (['', 'feature'], 'checkout_not_main'),
    (['', 'main', 'a' * 40, 'b' * 40 + '\trefs/heads/main'], 'pushed_revision_mismatch'),
])
def test_release_refuses_unpushed_or_unreviewed_code(answers, reason):
    with patch.object(deploy, 'command', side_effect=answers):
        with pytest.raises(deploy.DeploymentError, match=reason):
            deploy.pushed_revision()


def test_runtime_does_not_return_secret_values():
    from subprocess import CompletedProcess
    output = '\n state = running\n pid = 123\n TOKEN => secret-value\n PENNY_SOURCE_REVISION => ' + 'a' * 40
    with patch.object(deploy.subprocess, 'run', return_value=CompletedProcess([], 0, output, '')):
        result = deploy.runtime('com.penny.watcher')
    assert result['revision'] == 'a' * 40
    assert 'secret-value' not in str(result)

