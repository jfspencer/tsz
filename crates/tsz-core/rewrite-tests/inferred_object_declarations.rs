use std::sync::Arc;

use tsz::service::LanguageService;
use tsz::{CompileExitStatus, Compiler, CompilerOptions, SemanticCompletion, SourceInput};

fn options() -> CompilerOptions {
    CompilerOptions {
        target: "es2022".to_owned(),
        module: "esnext".to_owned(),
        declaration: true,
        emit_declaration_only: true,
        ..CompilerOptions::default()
    }
}

#[test]
fn inferred_object_declaration_matrix_matches_production_release() {
    let matrix: serde_json::Value =
        serde_json::from_str(include_str!("fixtures/inferred_object_declarations.json")).unwrap();
    assert_eq!(matrix["oracle_version"], "7.0.2");
    for case in matrix["cases"].as_array().unwrap() {
        let source = case["source"].as_str().unwrap();
        let expected = case["declaration"].as_str().unwrap();
        let mut inputs = vec![
            SourceInput::new("a.ts", source),
            SourceInput::new("z.ts", source),
        ];
        for _ in 0..2 {
            inputs.reverse();
            let output = Compiler::new().compile(inputs.clone(), &options());
            assert_eq!(
                output.exit_status,
                CompileExitStatus::Success,
                "{}: {output:?}",
                case["name"]
            );
            assert_eq!(output.semantic_completion, SemanticCompletion::Complete);
            assert!(output.diagnostics.is_empty());
            assert_eq!(output.emitted_files.len(), 2);
            for product in &output.emitted_files {
                assert!(product.declaration);
                assert_eq!(product.text, expected, "{}", case["name"]);
            }
        }
        let mut service = LanguageService::new(options());
        service.open("case.ts", Arc::<str>::from(source));
        for _ in 0..2 {
            let diagnostics = service.semantic_diagnostics("case.ts");
            assert!(diagnostics.diagnostics.is_empty());
            assert_eq!(
                diagnostics.semantic_completion,
                SemanticCompletion::Complete
            );
            let output = service.compile();
            assert_eq!(output.exit_status, CompileExitStatus::Success);
            assert_eq!(output.emitted_files[0].text, expected);
        }
    }
}

#[test]
fn declaration_rendering_does_not_claim_unfinished_signature_inference() {
    // Delete these nonclaims as generic function-like declarations, inferred
    // return values, and aliases acquire complete value/display summaries.
    for source in [
        "export const sink = { identity<T>(value: T): T { return value; } };",
        "export const renamed = { identity<U>(item: U): U { return item; } };",
        "export const sink = { write: (value: string) => value };",
        "export const sink = { write(value = 1) { return value; } };",
        "export const sink = { make(value: number) { return { value }; } };",
        "export const origin = { use(value: string) {} }; export const alias = origin;",
    ] {
        let output = Compiler::new().compile(vec![SourceInput::new("case.ts", source)], &options());
        assert_eq!(
            output.exit_status,
            CompileExitStatus::SemanticIncomplete,
            "{source}"
        );
        assert_eq!(output.semantic_completion, SemanticCompletion::Deferred);
        assert!(
            output.diagnostics.is_empty(),
            "{source}: {:?}",
            output.diagnostics
        );
        assert!(output.emitted_files.is_empty(), "{source}");
    }
}

#[test]
fn nonliteral_array_elements_keep_their_checked_type_display() {
    let output = Compiler::new().compile(
        vec![SourceInput::new(
            "case.ts",
            "export const item = {}; export const items = [item];",
        )],
        &options(),
    );
    assert_eq!(output.exit_status, CompileExitStatus::Success);
    assert!(output.diagnostics.is_empty());
    assert_eq!(
        output.emitted_files[0].text,
        "export declare const item: {};\nexport declare const items: {}[];\n"
    );
}
