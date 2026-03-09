import tempfile
import unittest
from pathlib import Path
from unittest import mock

import mavenLib


class MavenCommandTests(unittest.TestCase):
    def test_prefers_maven_on_path_when_available(self):
        with mock.patch('mavenLib.shutil.which', side_effect=lambda name: r'C:\tools\apache-maven\bin\mvn.cmd' if name == 'mvn.cmd' else None):
            self.assertEqual(['mvn.cmd'], mavenLib.resolve_maven_command('Windows', cwd='.'))

    def test_falls_back_to_wrapper_when_maven_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            wrapper_root = root / 'tooling'
            project_root = root / 'workspace' / 'sample'
            (wrapper_root / '.mvn' / 'wrapper').mkdir(parents=True)
            (wrapper_root / 'mvnw.cmd').write_text('@echo off\r\n', encoding='utf-8')
            (wrapper_root / '.mvn' / 'wrapper' / 'maven-wrapper.properties').write_text('distributionUrl=https://repo.maven.apache.org/maven2/...\n', encoding='utf-8')
            project_root.mkdir(parents=True)

            with mock.patch('mavenLib.shutil.which', return_value=None):
                command = mavenLib.resolve_maven_command('Windows', cwd=project_root, wrapper_root=wrapper_root)

            self.assertEqual([str(wrapper_root / 'mvnw.cmd')], command)

    def test_raises_when_neither_maven_nor_wrapper_is_available(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch('mavenLib.shutil.which', return_value=None):
                with self.assertRaises(FileNotFoundError):
                    mavenLib.resolve_maven_command('Windows', cwd=temp_dir, wrapper_root=temp_dir)

    def test_extracts_java_version_from_parent_pom_property(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            child_dir = root / 'module'
            child_dir.mkdir()

            (root / 'pom.xml').write_text(
                """<project xmlns=\"http://maven.apache.org/POM/4.0.0\">
  <modelVersion>4.0.0</modelVersion>
  <groupId>example</groupId>
  <artifactId>parent</artifactId>
  <version>1.0.0</version>
  <packaging>pom</packaging>
  <properties>
    <java.version>1.6</java.version>
  </properties>
</project>
""",
                encoding='utf-8',
            )
            (child_dir / 'pom.xml').write_text(
                """<project xmlns=\"http://maven.apache.org/POM/4.0.0\">
  <modelVersion>4.0.0</modelVersion>
  <parent>
    <groupId>example</groupId>
    <artifactId>parent</artifactId>
    <version>1.0.0</version>
  </parent>
  <artifactId>child</artifactId>
</project>
""",
                encoding='utf-8',
            )

            java_version, _, _ = mavenLib.extract_test_and_java_version_maven(child_dir)

        self.assertEqual('1.6', java_version)


if __name__ == '__main__':
    unittest.main()

