"""ZLUSV-200 read-only adapter boundary. Real control is disabled."""

CONTROL_MODE = "disabled"
READ_ONLY = True


def send_control_command(*_args: object, **_kwargs: object) -> None:
    raise RuntimeError("Real-vessel control is disabled; decision support is read-only")

