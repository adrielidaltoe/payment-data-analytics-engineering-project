import corvella


class TestCorvellaPackage:
    def test_import_has_module_docstring(self) -> None:
        assert corvella.__doc__
