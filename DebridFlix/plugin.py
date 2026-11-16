from Plugins.Plugin import PluginDescriptor

_app = None


def get_app():
    global _app
    if _app is None:
        from .core.service import App
        _app = App()
    return _app


def main(session, **kwargs):
    from .ui.common import enigma_locale
    from .ui.home import HomeScreen
    app = get_app()
    app.apply_language(enigma_locale())
    session.open(HomeScreen, app)


def Plugins(**kwargs):
    # read once by Enigma2 at startup: use the language setting / box language already here
    from .core.i18n import _, resolve, set_language
    try:
        from .core.settings import Settings
        from .ui.common import enigma_locale
        set_language(resolve(Settings().get("ui_language"), enigma_locale()))
    except Exception:
        pass
    return [PluginDescriptor(name="DebridFlix", description=_("Browse and play movies and series from your debrid services"),
                             where=[PluginDescriptor.WHERE_PLUGINMENU, PluginDescriptor.WHERE_EXTENSIONSMENU], icon="plugin.png", fnc=main)]
