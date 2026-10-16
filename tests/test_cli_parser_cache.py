"""kit.cli.main reuses one parser per (prog, sub_progs); results must match a fresh parser."""
import contextlib
import io
import time
import unittest

from kit import cli


class CachedParserTest(unittest.TestCase):
    def test_built_once_per_key(self):
        self.assertIs(cli._parser(), cli._parser())
        self.assertIsNot(cli._parser(), cli._parser(sub_progs={"rowscore": "kit-rowscore"}))

    def test_same_namespace_as_a_fresh_parser(self):
        argv = ["rowscore", "f.png", "--voxel-um", "9.362", "--reverse", "r.png"]
        self.assertEqual(vars(cli._parse(cli._parser(), argv)), vars(cli.build_parser().parse_args(argv)))

    def test_list_defaults_do_not_leak(self):
        argv = ["rowscore", "f.png", "--voxel-um", "9.362"]
        first = cli._parse(cli._parser(), argv)
        self.assertEqual(first.reverse, [])
        first.reverse.append("leaked")      # a handler mutating its list default
        self.assertEqual(cli._parse(cli._parser(), argv).reverse, [])

    def test_repeated_main_is_fast(self):
        t = time.perf_counter()
        for _ in range(20):
            with contextlib.redirect_stdout(io.StringIO()):
                cli.main(["prizes", "--json"])
        self.assertLess(time.perf_counter() - t, 5.0)


if __name__ == "__main__":
    unittest.main()
