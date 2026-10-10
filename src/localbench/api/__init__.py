"""Optional local HTTP transport. Importing localbench does not require API extras."""

def create_app(*, read_port=None):
    from .app import create_app as factory
    return factory(read_port=read_port)
