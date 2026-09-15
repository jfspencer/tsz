// Injected only for capture-contract tests, never into an oracle observation.
package harnessutil

import (
	"bytes"
	"encoding/json"
	"github.com/microsoft/typescript-go/internal/ast"
	"github.com/microsoft/typescript-go/internal/compiler"
	"github.com/microsoft/typescript-go/internal/core"
	"github.com/microsoft/typescript-go/internal/diagnostics"
	"github.com/microsoft/typescript-go/internal/parser"
	"github.com/microsoft/typescript-go/internal/vfs/vfstest"
	"os"
	"os/exec"
	"path/filepath"
	"testing"
	"testing/fstest"
)

func TestTszCaptureRawBytes(t *testing.T) {
	directory := t.TempDir()
	if err := os.Mkdir(filepath.Join(directory, "blobs"), 0o755); err != nil {
		t.Fatal(err)
	}
	input := &fstest.MapFile{Data: []byte{0, 128, 255, 13, 10}, Mode: 0o644}
	record := tszStoreInput(t, directory, "/.src/binary.ts", input)
	stored, err := os.ReadFile(filepath.Join(directory, "blobs", record.SHA256))
	if err != nil || !bytes.Equal(stored, input.Data) || record.ByteLength != 5 || record.Mode != 0o644 {
		t.Fatalf("input bytes or metadata changed: %+v, %v", record, err)
	}
}

func TestTszCaptureSharedBlobs(t *testing.T) {
	payload := bytes.Repeat([]byte{0, 128, 255, 13, 10}, 200_000)
	if childPath := os.Getenv("TSZ_CAPTURE_CONTRACT_CHILD_PATH"); childPath != "" {
		for range 8 {
			tszWriteInput(t, childPath, payload)
		}
		return
	}
	path := filepath.Join(t.TempDir(), "shared-blob")
	var children []*exec.Cmd
	for range 6 {
		child := exec.Command(os.Args[0], "-test.run=^TestTszCaptureSharedBlobs$")
		child.Env = append(os.Environ(), "TSZ_CAPTURE_CONTRACT_CHILD_PATH="+path)
		child.Stdout, child.Stderr = os.Stdout, os.Stderr
		if err := child.Start(); err != nil {
			t.Error(err)
			break
		}
		children = append(children, child)
	}
	for _, child := range children {
		if err := child.Wait(); err != nil {
			t.Error(err)
		}
	}
	stored, err := os.ReadFile(path)
	if err != nil || !bytes.Equal(stored, payload) {
		t.Fatalf("shared blob changed: %v", err)
	}
}

func TestTszCaptureCompletedResult(t *testing.T) {
	directory := t.TempDir()
	t.Setenv("TSZ_ORACLE_RESULT_DIR", directory)
	fs := NewOutputRecorderFS(vfstest.FromMap(map[string]any{}, true))
	raw := string([]byte{0, 128, 255, 13, 10})
	if err := fs.WriteFile("/out.js", raw); err != nil {
		t.Fatal(err)
	}
	source := parser.ParseSourceFile(ast.SourceFileParseOptions{FileName: "/unicode.ts"}, "// 😀\nlet x;", core.ScriptKindTS)
	diagnostic := ast.NewDiagnostic(source, core.NewTextRange(8, 11), diagnostics.Identifier_expected)
	diagnostic.AddMessageChain(ast.NewCompilerDiagnostic(diagnostics.Identifier_expected))
	diagnostic.AddRelatedInfo(ast.NewDiagnostic(source, core.NewTextRange(12, 13), diagnostics.Identifier_expected))
	result := &CompilationResult{
		Host:        createCompilerHost(fs, "/lib", "/"),
		Diagnostics: []*ast.Diagnostic{diagnostic}, Trace: "trace\r\n",
		Result: &compiler.EmitResult{EmitSkipped: false, Diagnostics: []*ast.Diagnostic{diagnostic}},
	}
	tszCaptureCompilationResult(t, "case", result)
	data, err := os.ReadFile(filepath.Join(directory, "invocations", "case.json"))
	if err != nil {
		t.Fatal(err)
	}
	var record struct {
		Outputs     []tszInputFile          `json:"outputs"`
		Diagnostics []tszCapturedDiagnostic `json:"diagnostics"`
		Trace       string                  `json:"trace"`
	}
	if err := json.Unmarshal(data, &record); err != nil {
		t.Fatal(err)
	}
	if len(record.Outputs) != 1 || record.Outputs[0].Path != "/out.js" || record.Trace != "trace\r\n" {
		t.Fatalf("lost output metadata: %+v", record)
	}
	stored, err := os.ReadFile(filepath.Join(directory, "blobs", record.Outputs[0].SHA256))
	if err != nil || string(stored) != raw {
		t.Fatalf("changed raw output: %v", err)
	}
	d := record.Diagnostics[0]
	if d.Start != 8 || d.Length != 3 || d.Text != "Identifier expected." || d.Code != 1003 || d.Category != "error" || len(d.MessageChain) != 1 || len(d.RelatedInformation) != 1 {
		t.Fatalf("lost diagnostic identity: %+v", d)
	}
	stored, err = os.ReadFile(filepath.Join(directory, "blobs", d.Source.SHA256))
	if err != nil || string(stored) != source.Text() {
		t.Fatal("changed diagnostic source bytes")
	}
	if result.Diagnostics[0] != diagnostic || diagnostic.Pos() != 8 || len(diagnostic.RelatedInformation()) != 1 {
		t.Fatal("capture mutated native result")
	}
	// A second capture must be byte-identical; no extra native queries run.
	tszCaptureCompilationResult(t, "case", result)
}
