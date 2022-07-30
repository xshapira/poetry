from __future__ import annotations

import ast

from configparser import ConfigParser
from pathlib import Path
from typing import Any
from typing import Iterable

from poetry.core.semver.version import Version


class SetupReader:
    """
    Class that reads a setup.py file without executing it.
    """

    DEFAULT = {
        "name": None,
        "version": None,
        "install_requires": [],
        "extras_require": {},
        "python_requires": None,
    }

    FILES = ["setup.py", "setup.cfg"]

    @classmethod
    def read_from_directory(cls, directory: str | Path) -> dict[str, list | dict]:
        if isinstance(directory, str):
            directory = Path(directory)

        result = cls.DEFAULT.copy()
        for filename in cls.FILES:
            filepath = directory / filename
            if not filepath.exists():
                continue

            read_file_func = getattr(cls(), "read_" + filename.replace(".", "_"))
            new_result = read_file_func(filepath)

            for key in result.keys():
                if new_result[key]:
                    result[key] = new_result[key]

        return result

    def read_setup_py(self, filepath: str | Path) -> dict[str, list | dict]:
        if isinstance(filepath, str):
            filepath = Path(filepath)

        with filepath.open(encoding="utf-8") as f:
            content = f.read()

        body = ast.parse(content).body

        setup_call, body = self._find_setup_call(body)
        if not setup_call:
            return self.DEFAULT

        result = {"name": self._find_single_string(setup_call, body, "name")}
        result["version"] = self._find_single_string(setup_call, body, "version")
        result["install_requires"] = self._find_install_requires(setup_call, body)
        result["extras_require"] = self._find_extras_require(setup_call, body)
        result["python_requires"] = self._find_single_string(
            setup_call, body, "python_requires"
        )

        return result

    def read_setup_cfg(self, filepath: str | Path) -> dict[str, list | dict]:
        parser = ConfigParser()

        parser.read(str(filepath))

        name = None
        version = None
        if parser.has_option("metadata", "name"):
            name = parser.get("metadata", "name")

        if parser.has_option("metadata", "version"):
            version = Version.parse(parser.get("metadata", "version")).text

        install_requires = []
        extras_require = {}
        python_requires = None
        if parser.has_section("options"):
            if parser.has_option("options", "install_requires"):
                for dep in parser.get("options", "install_requires").split("\n"):
                    if dep := dep.strip():
                        install_requires.append(dep)

            if parser.has_option("options", "python_requires"):
                python_requires = parser.get("options", "python_requires")

        if parser.has_section("options.extras_require"):
            for group in parser.options("options.extras_require"):
                extras_require[group] = []
                deps = parser.get("options.extras_require", group)
                for dep in deps.split("\n"):
                    if dep := dep.strip():
                        extras_require[group].append(dep)

        return {
            "name": name,
            "version": version,
            "install_requires": install_requires,
            "extras_require": extras_require,
            "python_requires": python_requires,
        }

    def _find_setup_call(
        self, elements: list[Any]
    ) -> tuple[ast.Call | None, list[Any] | None]:
        funcdefs = []
        for i, element in enumerate(elements):
            if isinstance(element, ast.If) and i == len(elements) - 1:
                # Checking if the last element is an if statement
                # and if it is 'if __name__ == "__main__"' which
                # could contain the call to setup()
                test = element.test
                if not isinstance(test, ast.Compare):
                    continue

                left = test.left
                if not isinstance(left, ast.Name):
                    continue

                if left.id != "__name__":
                    continue

                setup_call, body = self._find_sub_setup_call([element])
                if not setup_call:
                    continue

                return setup_call, body + elements
            if not isinstance(element, ast.Expr):
                if isinstance(element, ast.FunctionDef):
                    funcdefs.append(element)

                continue

            value = element.value
            if not isinstance(value, ast.Call):
                continue

            func = value.func
            if not (isinstance(func, ast.Name) and func.id == "setup") and not (
                isinstance(func, ast.Attribute)
                and hasattr(func.value, "id")
                and func.value.id == "setuptools"
                and func.attr == "setup"
            ):
                continue

            return value, elements

        # Nothing, we inspect the function definitions
        return self._find_sub_setup_call(funcdefs)

    def _find_sub_setup_call(
        self, elements: list[Any]
    ) -> tuple[ast.Call | None, list[Any] | None]:
        for element in elements:
            if not isinstance(element, (ast.FunctionDef, ast.If)):
                continue

            setup_call = self._find_setup_call(element.body)
            if setup_call != (None, None):
                setup_call, body = setup_call

                body = elements + body

                return setup_call, body

        return None, None

    def _find_install_requires(self, call: ast.Call, body: Iterable[Any]) -> list[str]:
        install_requires = []
        value = self._find_in_call(call, "install_requires")
        if value is None:
            # Trying to find in kwargs
            kwargs = self._find_call_kwargs(call)

            if kwargs is None or not isinstance(kwargs, ast.Name):
                return install_requires

            variable = self._find_variable_in_body(body, kwargs.id)
            if not isinstance(variable, (ast.Dict, ast.Call)):
                return install_requires

            if isinstance(variable, ast.Call):
                if not isinstance(variable.func, ast.Name):
                    return install_requires

                if variable.func.id != "dict":
                    return install_requires

                value = self._find_in_call(variable, "install_requires")
            else:
                value = self._find_in_dict(variable, "install_requires")

        if value is None:
            return install_requires

        if isinstance(value, ast.List):
            install_requires.extend(el.s for el in value.elts)
        elif isinstance(value, ast.Name):
            variable = self._find_variable_in_body(body, value.id)

            if variable is not None and isinstance(variable, ast.List):
                install_requires.extend(el.s for el in variable.elts)
        return install_requires

    def _find_extras_require(
        self, call: ast.Call, body: Iterable[Any]
    ) -> dict[str, list]:
        extras_require = {}
        value = self._find_in_call(call, "extras_require")
        if value is None:
            # Trying to find in kwargs
            kwargs = self._find_call_kwargs(call)

            if kwargs is None or not isinstance(kwargs, ast.Name):
                return extras_require

            variable = self._find_variable_in_body(body, kwargs.id)
            if not isinstance(variable, (ast.Dict, ast.Call)):
                return extras_require

            if isinstance(variable, ast.Call):
                if not isinstance(variable.func, ast.Name):
                    return extras_require

                if variable.func.id != "dict":
                    return extras_require

                value = self._find_in_call(variable, "extras_require")
            else:
                value = self._find_in_dict(variable, "extras_require")

        if value is None:
            return extras_require

        if isinstance(value, ast.Dict):
            for key, val in zip(value.keys, value.values):
                if isinstance(val, ast.Name):
                    val = self._find_variable_in_body(body, val.id)

                if isinstance(val, ast.List):
                    extras_require[key.s] = [e.s for e in val.elts]
        elif isinstance(value, ast.Name):
            variable = self._find_variable_in_body(body, value.id)

            if variable is None or not isinstance(variable, ast.Dict):
                return extras_require

            for key, val in zip(variable.keys, variable.values):
                if isinstance(val, ast.Name):
                    val = self._find_variable_in_body(body, val.id)

                if isinstance(val, ast.List):
                    extras_require[key.s] = [e.s for e in val.elts]

        return extras_require

    def _find_single_string(
        self, call: ast.Call, body: list[Any], name: str
    ) -> str | None:
        value = self._find_in_call(call, name)
        if value is None:
            # Trying to find in kwargs
            kwargs = self._find_call_kwargs(call)

            if kwargs is None or not isinstance(kwargs, ast.Name):
                return None

            variable = self._find_variable_in_body(body, kwargs.id)
            if not isinstance(variable, (ast.Dict, ast.Call)):
                return None

            if isinstance(variable, ast.Call):
                if not isinstance(variable.func, ast.Name):
                    return None

                if variable.func.id != "dict":
                    return None

                value = self._find_in_call(variable, name)
            else:
                value = self._find_in_dict(variable, name)

        if value is None:
            return None

        if isinstance(value, ast.Str):
            return value.s
        elif isinstance(value, ast.Name):
            variable = self._find_variable_in_body(body, value.id)

            if variable is not None and isinstance(variable, ast.Str):
                return variable.s

    def _find_in_call(self, call: ast.Call, name: str) -> Any | None:
        return next(
            (keyword.value for keyword in call.keywords if keyword.arg == name),
            None,
        )

    def _find_call_kwargs(self, call: ast.Call) -> Any | None:
        kwargs = None
        for keyword in call.keywords:
            if keyword.arg is None:
                kwargs = keyword.value

        return kwargs

    def _find_variable_in_body(self, body: Iterable[Any], name: str) -> Any | None:
        found = None
        for elem in body:
            if found:
                break

            if not isinstance(elem, ast.Assign):
                continue

            for target in elem.targets:
                if not isinstance(target, ast.Name):
                    continue

                if target.id == name:
                    return elem.value

    def _find_in_dict(self, dict_: ast.Dict | ast.Call, name: str) -> Any | None:
        return next(
            (
                val
                for key, val in zip(dict_.keys, dict_.values)
                if isinstance(key, ast.Str) and key.s == name
            ),
            None,
        )
