"""Windows system audio helpers for Silva."""

import sys

from silva.config import load_config


def ensure_audible() -> None:
    """Unmute speakers only. Does not force volume higher unless configured."""
    if sys.platform != "win32":
        return

    config = load_config()
    if not config.get("auto_unmute", True):
        return

    try:
        from comtypes import CLSCTX_ALL
        from ctypes import cast, POINTER
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

        try:
            from silva.media.devices import poll_audio_devices

            poll_audio_devices()
        except Exception:
            pass

        speakers = AudioUtilities.GetSpeakers()
        if speakers is None:
            return

        interface = speakers.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        volume_control = cast(interface, POINTER(IAudioEndpointVolume))

        if volume_control.GetMute():
            volume_control.SetMute(0, None)

        if config.get("auto_boost_system_volume", False):
            cap = float(config.get("system_volume_cap", 0.65))
            current = volume_control.GetMasterVolumeLevelScalar()
            if current > cap:
                volume_control.SetMasterVolumeLevelScalar(cap, None)
    except Exception:
        pass
