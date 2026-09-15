use std::fs;
use std::path::Path;

use tempfile::TempDir;
use tsz::config::{ProjectRequest, ProjectSelection, resolve_project};
use tsz::host::SystemHost;
use tsz::{CompileExitStatus, Compiler, CompilerOptions, SemanticCompletion, SourceInput};

fn project(root: &Path) -> tsz::CompileOutput {
    let resolved = resolve_project(
        &SystemHost::new(root),
        &ProjectRequest::new(ProjectSelection::Project(root.to_path_buf())),
    );
    let options = resolved.options.clone();
    Compiler::new().compile_resolved(resolved, &options)
}

#[test]
fn declaration_only_selects_exact_products_across_names_extensions_and_root_order() {
    for name in ["value", "renamed"] {
        for extension in ["ts", "mts", "cts"] {
            let source = format!("export const {name}: number = 1;\n");
            let mut inputs = vec![
                SourceInput::new(format!("a.{extension}"), source.clone()),
                SourceInput::new(format!("z.{extension}"), source.clone()),
            ];
            for reverse in [false, true] {
                if reverse {
                    inputs.reverse();
                }
                for declaration_only in [false, true] {
                    let output = Compiler::new().compile(
                        inputs.clone(),
                        &CompilerOptions {
                            declaration: true,
                            emit_declaration_only: declaration_only,
                            ..CompilerOptions::default()
                        },
                    );
                    assert_eq!(output.semantic_completion, SemanticCompletion::Complete);
                    assert_eq!(output.exit_status, CompileExitStatus::Success);
                    assert!(output.diagnostics.is_empty(), "{:?}", output.diagnostics);
                    assert_eq!(
                        output.emitted_files.len(),
                        if declaration_only { 2 } else { 4 }
                    );
                    for file in output.emitted_files.iter().filter(|file| file.declaration) {
                        assert_eq!(file.text, format!("export declare const {name}: number;\n"));
                        assert_eq!(
                            file.path.extension().unwrap(),
                            extension,
                            "declaration extension follows the input module kind"
                        );
                    }
                }
            }
        }
    }
}

#[test]
fn declaration_only_validation_and_exit_status_match_release_option_matrix() {
    // TypeScript 7.0.2: compiler/program.go:GetDiagnosticsOfAnyProgram and
    // compiler/emitter.go: emit methods mark skipped only for an actual target.
    for declaration in [false, true] {
        for no_emit in [false, true] {
            for no_emit_on_error in [false, true] {
                let output = Compiler::new().compile(
                    vec![SourceInput::new(
                        "case.ts",
                        "export const value: string = 1;\n",
                    )],
                    &CompilerOptions {
                        declaration,
                        no_emit,
                        no_emit_on_error,
                        emit_declaration_only: true,
                        ..CompilerOptions::default()
                    },
                );
                assert_eq!(output.semantic_completion, SemanticCompletion::Complete);
                let [diagnostic] = output.diagnostics.as_slice() else {
                    panic!("unexpected diagnostics: {:?}", output.diagnostics);
                };
                assert_eq!(diagnostic.code, if declaration { 2322 } else { 5069 });
                if !declaration {
                    assert_eq!(
                        diagnostic.message_text,
                        "Option 'emitDeclarationOnly' cannot be specified without specifying option 'declaration' or option 'composite'."
                    );
                    assert_eq!(
                        (
                            diagnostic.file.as_str(),
                            diagnostic.start,
                            diagnostic.length
                        ),
                        ("", 0, 0)
                    );
                }
                assert_eq!(
                    output.emitted_files.len(),
                    usize::from(declaration && !no_emit && !no_emit_on_error)
                );
                assert_eq!(
                    output.exit_status,
                    if no_emit_on_error || no_emit && declaration {
                        CompileExitStatus::DiagnosticsPresentOutputsSkipped
                    } else {
                        CompileExitStatus::DiagnosticsPresentOutputsGenerated
                    }
                );
            }
        }
    }
}

#[test]
fn inherited_declaration_only_option_uses_entry_config_span_and_output_directory() {
    let fixture = TempDir::new().unwrap();
    fs::write(
        fixture.path().join("base.json"),
        r#"{"compilerOptions":{"emitDeclarationOnly":true}}"#,
    )
    .unwrap();
    fs::write(
        fixture.path().join("case.ts"),
        "export function identity<T>(value: T): T { return value; }\n",
    )
    .unwrap();
    let config = r#"{"extends":"./base.json","compilerOptions":{"declaration":true,"declarationDir":"types"},"files":["case.ts"]}"#;
    fs::write(fixture.path().join("tsconfig.json"), config).unwrap();
    let output = project(fixture.path());
    assert_eq!(output.exit_status, CompileExitStatus::Success);
    assert_eq!(output.emitted_files.len(), 1);
    let file = &output.emitted_files[0];
    assert!(file.path.ends_with("types/case.d.ts"));
    assert_eq!(
        file.text,
        "export declare function identity<T>(value: T): T;\n"
    );

    let invalid = config.replace("\"declaration\":true", "\"declaration\":false");
    fs::write(fixture.path().join("tsconfig.json"), &invalid).unwrap();
    let output = project(fixture.path());
    let diagnostic = output
        .diagnostics
        .iter()
        .find(|diagnostic| diagnostic.code == 5069)
        .unwrap();
    assert_eq!(diagnostic.file, "tsconfig.json");
    assert_eq!(
        diagnostic.start,
        invalid.find("\"declaration\"").unwrap() as u32
    );
    assert_eq!(diagnostic.length, "\"declaration\"".len() as u32);
    assert!(output.emitted_files.is_empty());
}

#[test]
fn declaration_only_does_not_depend_on_an_unrequested_javascript_map() {
    for declaration_map in [false, true] {
        let output = Compiler::new().compile(
            vec![SourceInput::new(
                "case.ts",
                "export const item: number = 1;\n",
            )],
            &CompilerOptions {
                declaration: true,
                emit_declaration_only: true,
                source_map: true,
                declaration_map,
                ..CompilerOptions::default()
            },
        );
        assert!(output.diagnostics.is_empty());
        assert_eq!(
            output.semantic_completion,
            if declaration_map {
                SemanticCompletion::Deferred
            } else {
                SemanticCompletion::Complete
            }
        );
        assert_eq!(output.emitted_files.len(), usize::from(!declaration_map));
    }
}

#[test]
fn composite_is_recognized_but_unimplemented_work_cannot_be_claimed() {
    let fixture = TempDir::new().unwrap();
    fs::write(fixture.path().join("case.ts"), "export const item = 1;\n").unwrap();
    for composite in [false, true] {
        fs::write(fixture.path().join("tsconfig.json"), format!(r#"{{"compilerOptions":{{"emitDeclarationOnly":true,"composite":{composite}}},"files":["case.ts"]}}"#)).unwrap();
        let output = project(fixture.path());
        if composite {
            assert_eq!(output.semantic_completion, SemanticCompletion::Deferred);
            assert!(output.diagnostics.is_empty(), "{:?}", output.diagnostics);
        } else {
            assert_eq!(output.diagnostics[0].code, 5069);
        }
        assert!(output.emitted_files.is_empty());
    }
}

#[test]
fn option_dependency_span_uses_first_authored_key_including_duplicates() {
    let fixture = TempDir::new().unwrap();
    fs::write(fixture.path().join("case.ts"), "export const item = 1;\n").unwrap();
    for members in [
        r#""emitDeclarationOnly":true,"declaration":false"#,
        r#""declaration":false,"emitDeclarationOnly":true"#,
        r#""emitDeclarationOnly":false,"declaration":false,"emitDeclarationOnly":true"#,
    ] {
        let config = format!(r#"{{"compilerOptions":{{{members}}},"files":["case.ts"]}}"#);
        fs::write(fixture.path().join("tsconfig.json"), &config).unwrap();
        let output = project(fixture.path());
        let [diagnostic] = output.diagnostics.as_slice() else {
            panic!("unexpected diagnostics: {:?}", output.diagnostics);
        };
        assert_eq!(diagnostic.code, 5069);
        assert_eq!(diagnostic.start, "{\"compilerOptions\":{".len() as u32);
        assert_eq!(diagnostic.length, members.find(':').unwrap() as u32);
        assert_eq!(
            output.exit_status,
            CompileExitStatus::DiagnosticsPresentOutputsGenerated
        );
    }
}
