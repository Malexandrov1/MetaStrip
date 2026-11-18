import sys


def main() -> int:
    try:
        from PySide6.QtWidgets import QApplication

        from app import __version__
        from app.ui.main_window import MainWindow
        from app.utils.logging_config import configure_logging
    except ImportError as exc:
        print(
            f"MetaStrip could not start: missing dependency ({exc.name}).\n"
            "Install the application with: python -m pip install -e .",
            file=sys.stderr,
        )
        return 1

    configure_logging()
    app = QApplication(sys.argv)
    app.setApplicationName("MetaStrip")
    app.setOrganizationName("MetaStrip")
    app.setApplicationVersion(__version__)
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
