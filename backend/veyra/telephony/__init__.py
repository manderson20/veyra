# SPDX-License-Identifier: AGPL-3.0-or-later
"""Telephony engine integration."""

from __future__ import annotations

from veyra.core.config import Settings
from veyra.telephony.adapter import NullAdapter, TelephonyAdapter


def get_adapter(settings: Settings) -> TelephonyAdapter:
    if settings.telephony_engine == "asterisk":
        from veyra.telephony.asterisk.adapter import AsteriskAdapter

        return AsteriskAdapter(
            settings.asterisk_ari_url,
            settings.asterisk_ari_username,
            settings.asterisk_ari_password_file,
            prompts_dir=settings.prompts_dir,
            mailqueue_command=settings.mailqueue_command,
        )
    return NullAdapter()
