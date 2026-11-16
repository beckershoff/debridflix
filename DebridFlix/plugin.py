from Plugins.Plugin import PluginDescriptor

_app = None


def get_app():
    global _app
    if _app is None:
        from .core.service import App
        _app = App()
    return _app


def main(session, **kwargs):
    from .ui.home import HomeScreen
    session.open(HomeScreen, get_app())


def Plugins(**kwargs):
    return [PluginDescriptor(name="DebridFlix", description="Browse and play from Orion and your debrid services",
                             where=[PluginDescriptor.WHERE_PLUGINMENU, PluginDescriptor.WHERE_EXTENSIONSMENU], icon="plugin.png", fnc=main)]
