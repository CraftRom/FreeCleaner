"""FreeCleaner launcher (keeps python app.py working)."""

from freecleaner.app import Cleaner


def main() -> None:
    app = Cleaner()
    app.mainloop()


if __name__ == "__main__":
    main()
