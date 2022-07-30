from __future__ import annotations

from typing import TYPE_CHECKING

from cleo.commands.command import Command as BaseCommand


if TYPE_CHECKING:
    from poetry.console.application import Application
    from poetry.poetry import Poetry


class Command(BaseCommand):
    loggers: list[str] = []

    _poetry: Poetry | None = None

    @property
    def poetry(self) -> Poetry:
        return self.get_application().poetry if self._poetry is None else self._poetry

    def set_poetry(self, poetry: Poetry) -> None:
        self._poetry = poetry

    def get_application(self) -> Application:
        return self.application

    def reset_poetry(self) -> None:
        self.get_application().reset_poetry()
