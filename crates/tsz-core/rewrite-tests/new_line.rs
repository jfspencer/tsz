use tsz::{CompileExitStatus, Compiler, CompilerOptions, SourceInput};

#[test]
fn newline_products_match_the_production_oracle() {
    let matrix: serde_json::Value =
        serde_json::from_str(include_str!("fixtures/new_line.json")).unwrap();
    assert_eq!(matrix["oracle_version"], "7.0.2");
    let mut failures = Vec::new();
    for case in matrix["cases"].as_array().unwrap() {
        let options = CompilerOptions {
            target: "es2022".into(),
            module: case["module"].as_str().unwrap().into(),
            new_line: case["new_line"].as_str().unwrap().into(),
            declaration: true,
            ..CompilerOptions::default()
        };
        let output = Compiler::new().compile(
            vec![SourceInput::new(
                "case.ts",
                case["source"].as_str().unwrap(),
            )],
            &options,
        );
        let products: std::collections::BTreeMap<_, _> = output
            .emitted_files
            .iter()
            .map(|file| (file.path.to_str().unwrap(), file.text.as_str()))
            .collect();
        if output.exit_status != CompileExitStatus::Success
            || !output.diagnostics.is_empty()
            || serde_json::to_value(&products).unwrap() != case["products"]
        {
            failures.push(format!(
                "{}: {:?}\nactual: {products:?}\nexpected: {}",
                case["name"], output.exit_status, case["products"]
            ));
        }
    }
    assert!(failures.is_empty(), "{}", failures.join("\n"));
}

#[test]
fn newlines_remain_stable_across_root_order_and_service_compilations() {
    let matrix: serde_json::Value =
        serde_json::from_str(include_str!("fixtures/new_line.json")).unwrap();
    let case = matrix["cases"]
        .as_array()
        .unwrap()
        .iter()
        .find(|case| case["name"] == "template_object_crlf")
        .unwrap();
    let source = case["source"].as_str().unwrap();
    let options = CompilerOptions {
        declaration: true,
        new_line: "crlf".into(),
        ..CompilerOptions::default()
    };
    let mut roots = vec![
        SourceInput::new("a.ts", source),
        SourceInput::new("z.ts", source),
    ];
    let check = |output: tsz::CompileOutput| {
        assert_eq!(output.exit_status, CompileExitStatus::Success);
        assert!(output.diagnostics.is_empty());
        assert_eq!(output.emitted_files.len(), 4);
        for product in output.emitted_files {
            let key = if product.declaration {
                "case.d.ts"
            } else {
                "case.js"
            };
            assert_eq!(product.text, case["products"][key].as_str().unwrap());
        }
    };
    let mut service = tsz::service::LanguageService::new(options.clone());
    for input in &roots {
        service.open(input.path.to_str().unwrap(), input.text.clone());
    }
    for _ in 0..2 {
        roots.reverse();
        check(Compiler::new().compile(roots.clone(), &options));
        check(service.compile());
    }
}
