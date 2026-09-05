import pytest
from routers.admin_commands import handle_admin_command, is_authorized_admin


@pytest.mark.anyio
async def test_admin_commands_status():
    is_cmd, reply = await handle_admin_command("923306874242@s.whatsapp.net", "/status", send_whatsapp=False)
    assert is_cmd is True
    assert "Bot Status" in reply


@pytest.mark.anyio
async def test_admin_commands_activate_deactivate():
    is_cmd, reply = await handle_admin_command("923306874242@s.whatsapp.net", "/deactivate", send_whatsapp=False)
    assert is_cmd is True
    assert "Deactivated" in reply

    is_cmd, reply = await handle_admin_command("923306874242@s.whatsapp.net", "/activate", send_whatsapp=False)
    assert is_cmd is True
    assert "Activated" in reply


@pytest.mark.anyio
async def test_admin_commands_help():
    is_cmd, reply = await handle_admin_command("923306874242@s.whatsapp.net", "/help", send_whatsapp=False)
    assert is_cmd is True
    assert "Admin Commands" in reply


@pytest.mark.anyio
async def test_admin_commands_mute_unmute():
    is_cmd, reply = await handle_admin_command("923306874242@s.whatsapp.net", "mute 923119998877", send_whatsapp=False)
    assert is_cmd is True
    assert "Customer Muted" in reply

    is_cmd, reply = await handle_admin_command("923306874242@s.whatsapp.net", "unmute 923119998877", send_whatsapp=False)
    assert is_cmd is True
    assert "Customer Unmuted" in reply


@pytest.mark.anyio
async def test_admin_commands_secret_prefix():
    # Secret keyword agent47 should work even from unknown numbers
    is_cmd, reply = await handle_admin_command("929990001111@s.whatsapp.net", "agent47status", send_whatsapp=False)
    assert is_cmd is True
    assert "Bot Status" in reply


def test_is_authorized_admin():
    assert is_authorized_admin("923306874242@s.whatsapp.net", "status") is True
    assert is_authorized_admin("923306874242:1@s.whatsapp.net", "status") is True
    assert is_authorized_admin("923306874242:2@c.us", "status") is True
    assert is_authorized_admin("03306874242@s.whatsapp.net", "status") is True
    assert is_authorized_admin("69630278291529@lid", "status") is True
    assert is_authorized_admin("random_lid@lid", "status", remote_jid_alt="923306874242:1@s.whatsapp.net") is True
    assert is_authorized_admin("923999999999@s.whatsapp.net", "agent47activate") is True
    assert is_authorized_admin("923999999999@s.whatsapp.net", "/status") is False


@pytest.mark.anyio
async def test_admin_commands_variations():
    # Exclamation mark prefix
    is_cmd, reply = await handle_admin_command("923306874242:1@s.whatsapp.net", "!status", send_whatsapp=False)
    assert is_cmd is True
    assert "Bot Status" in reply

    # Bot status phrase
    is_cmd, reply = await handle_admin_command("923306874242:2@s.whatsapp.net", "bot status", send_whatsapp=False)
    assert is_cmd is True
    assert "Bot Status" in reply

    # Bot off phrase
    is_cmd, reply = await handle_admin_command("923306874242:1@s.whatsapp.net", "bot off", send_whatsapp=False)
    assert is_cmd is True
    assert "Deactivated" in reply

    # Bot on phrase
    is_cmd, reply = await handle_admin_command("923306874242:1@s.whatsapp.net", "bot on", send_whatsapp=False)
    assert is_cmd is True
    assert "Activated" in reply

