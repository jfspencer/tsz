use std::fs;
use std::process::Command;

#[test]
fn command_line_declaration_only_uses_the_shared_option_schema_and_product_plan() {
    for name in ["item", "renamed"] {
        for enabled in ["true", "false"] {
            let fixture = tempfile::tempdir().unwrap();
            fs::write(
                fixture.path().join("case.ts"),
                format!("export const {name}: number = 1;\n"),
            )
            .unwrap();
            let output = Command::new(env!("CARGO_BIN_EXE_tsz"))
                .current_dir(fixture.path())
                .args([
                    "--ignoreConfig",
                    "--pretty",
                    "false",
                    "--declaration",
                    "--emitDeclarationOnly",
                    enabled,
                    "case.ts",
                ])
                .output()
                .unwrap();
            assert_eq!(output.status.code(), Some(0), "{output:?}");
            assert!(output.stdout.is_empty());
            assert!(output.stderr.is_empty());
            assert_eq!(fixture.path().join("case.js").exists(), enabled == "false");
            assert_eq!(
                fs::read_to_string(fixture.path().join("case.d.ts")).unwrap(),
                format!("export declare const {name}: number;\n")
            );
        }
    }
}

#[test]
fn invalid_declaration_only_reports_only_option_error_even_with_no_emit() {
    let fixture = tempfile::tempdir().unwrap();
    fs::write(
        fixture.path().join("case.ts"),
        "export const item: string = 1;\n",
    )
    .unwrap();
    for no_emit in [false, true] {
        let mut command = Command::new(env!("CARGO_BIN_EXE_tsz"));
        command.current_dir(fixture.path()).args([
            "--ignoreConfig",
            "--pretty",
            "false",
            "--emitDeclarationOnly",
            "case.ts",
        ]);
        if no_emit {
            command.arg("--noEmit");
        }
        let output = command.output().unwrap();
        assert_eq!(output.status.code(), Some(2));
        assert!(output.stderr.is_empty());
        assert_eq!(
            String::from_utf8(output.stdout).unwrap(),
            "error TS5069: Option 'emitDeclarationOnly' cannot be specified without specifying option 'declaration' or option 'composite'.\n"
        );
        assert!(!fixture.path().join("case.js").exists());
        assert!(!fixture.path().join("case.d.ts").exists());
    }
}
