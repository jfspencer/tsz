use std::{fs, process::Command};

#[test]
fn newline_cli_and_config_results_match_production_options() {
    let rows: serde_json::Value = serde_json::from_str(include_str!(
        "../../tsz-core/rewrite-tests/fixtures/new_line_options.json"
    ))
    .unwrap();
    for row in rows.as_array().unwrap() {
        let fixture = tempfile::tempdir().unwrap();
        fs::write(fixture.path().join("case.ts"), "export const value = 1;\n").unwrap();
        let mut command = Command::new(env!("CARGO_BIN_EXE_tsz"));
        command
            .current_dir(fixture.path())
            .args(["--pretty", "false"]);
        if row["kind"] == "cli" {
            command.args([
                "--ignoreConfig",
                "--NeWLiNe",
                row["value"].as_str().unwrap(),
                "case.ts",
            ]);
        } else {
            fs::write(
                fixture.path().join("tsconfig.json"),
                format!(
                    "{{\"compilerOptions\": {{\"newLine\": {}}}, \"files\": [\"case.ts\"]}}",
                    row["value"]
                ),
            )
            .unwrap();
            command.args(["-p", "tsconfig.json"]);
        }
        let result = command.output().unwrap();
        assert_eq!(
            result.status.code(),
            Some(row["exit"].as_i64().unwrap() as i32),
            "{row}: {result:?}"
        );
        assert_eq!(
            result.stdout,
            row["stdout"].as_str().unwrap().as_bytes(),
            "{row}"
        );
        assert!(result.stderr.is_empty(), "{row}: {result:?}");
        let product = fs::read(fixture.path().join("case.js")).ok();
        assert_eq!(
            product.as_deref(),
            row["js"].as_str().map(str::as_bytes),
            "{row}"
        );
    }
}

#[test]
fn cli_overrides_inherited_newlines_and_null_clears_them() {
    for (configured, command_line, expected) in [
        ("{}", None, "\r\n"),
        ("{\"newLine\":null}", None, "\n"),
        ("{\"newLine\":\"lf\"}", None, "\n"),
        ("{}", Some("lf"), "\n"),
        ("{\"newLine\":\"lf\"}", Some(" CRLF "), "\r\n"),
    ] {
        let fixture = tempfile::tempdir().unwrap();
        fs::write(fixture.path().join("case.ts"), "export const value = 1;\n").unwrap();
        fs::write(
            fixture.path().join("base.json"),
            "{\"compilerOptions\":{\"newLine\":\"crlf\"}}",
        )
        .unwrap();
        fs::write(fixture.path().join("tsconfig.json"), format!("{{\"extends\":\"./base.json\",\"compilerOptions\":{configured},\"files\":[\"case.ts\"]}}")).unwrap();
        let mut command = Command::new(env!("CARGO_BIN_EXE_tsz"));
        command
            .current_dir(fixture.path())
            .args(["-p", "tsconfig.json", "--pretty", "false"]);
        if let Some(value) = command_line {
            command.args(["--newLine", value]);
        }
        let result = command.output().unwrap();
        assert!(result.status.success(), "{result:?}");
        assert!(result.stdout.is_empty());
        assert!(result.stderr.is_empty());
        assert_eq!(
            fs::read(fixture.path().join("case.js")).unwrap(),
            format!("export const value = 1;{expected}").as_bytes()
        );
    }
}
