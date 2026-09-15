// Reporting-only capture of the native harness's already completed result.
package harnessutil

import (
	"encoding/json"
	"os"
	"path/filepath"
	"sort"
	"testing"
	"testing/fstest"

	"github.com/microsoft/typescript-go/internal/ast"
	"github.com/microsoft/typescript-go/internal/locale"
)

type tszCapturedDiagnostic struct {
	Source             *tszInputFile           `json:"source"`
	Start              int                     `json:"byte_start"`
	Length             int                     `json:"byte_length"`
	Code               int32                   `json:"code"`
	Category           string                  `json:"category"`
	Text               string                  `json:"text"`
	MessageChain       []tszCapturedDiagnostic `json:"message_chain"`
	RelatedInformation []tszCapturedDiagnostic `json:"related_information"`
	Unnecessary        bool                    `json:"reports_unnecessary"`
	Deprecated         bool                    `json:"reports_deprecated"`
	SkippedOnNoEmit    bool                    `json:"skipped_on_no_emit"`
}

func tszCaptureDiagnostics(t *testing.T, directory string, diagnostics []*ast.Diagnostic) []tszCapturedDiagnostic {
	records := make([]tszCapturedDiagnostic, 0, len(diagnostics))
	for _, diagnostic := range diagnostics {
		var source *tszInputFile
		if file := diagnostic.File(); file != nil {
			entry := tszStoreInput(t, directory, file.FileName(), &fstest.MapFile{Data: []byte(file.Text())})
			source = &entry
		}
		records = append(records, tszCapturedDiagnostic{
			Source: source, Start: diagnostic.Pos(), Length: diagnostic.Len(), Code: diagnostic.Code(),
			Category: diagnostic.Category().Name(), Text: diagnostic.Localize(locale.Default),
			MessageChain:       tszCaptureDiagnostics(t, directory, diagnostic.MessageChain()),
			RelatedInformation: tszCaptureDiagnostics(t, directory, diagnostic.RelatedInformation()),
			Unnecessary:        diagnostic.ReportsUnnecessary(), Deprecated: diagnostic.ReportsDeprecated(),
			SkippedOnNoEmit: diagnostic.SkippedOnNoEmit(),
		})
	}
	return records
}

func tszCaptureCompilationResult(t *testing.T, invocation string, result *CompilationResult) {
	t.Helper()
	directory := os.Getenv("TSZ_ORACLE_RESULT_DIR")
	if directory == "" {
		t.Fatal("missing TSZ_ORACLE_RESULT_DIR")
	}
	for _, child := range []string{"blobs", "invocations"} {
		if err := os.MkdirAll(filepath.Join(directory, child), 0o755); err != nil {
			t.Fatal(err)
		}
	}
	// Observe the output recorder directly: JS, DTS, maps, JSON and build-info
	// bytes are retained even when an output is absent from classified maps.
	fs, ok := result.Host.FS().(*OutputRecorderFS)
	if !ok {
		t.Fatal("native result no longer uses OutputRecorderFS")
	}
	outputs := make([]tszInputFile, 0)
	for _, file := range fs.Outputs() {
		outputs = append(outputs, tszStoreInput(t, directory, file.UnitName, &fstest.MapFile{Data: []byte(file.Content)}))
	}
	sort.Slice(outputs, func(i, j int) bool { return outputs[i].Path < outputs[j].Path })
	var emit any // null retains the distinction between no emit result and empty emit.
	if result.Result != nil {
		emit = struct {
			Skipped     bool                    `json:"skipped"`
			Diagnostics []tszCapturedDiagnostic `json:"diagnostics"`
			Files       []string                `json:"reported_files"`
		}{result.Result.EmitSkipped, tszCaptureDiagnostics(t, directory, result.Result.Diagnostics), result.Result.EmittedFiles}
	}
	record := struct {
		Schema      int                     `json:"schema"`
		Invocation  string                  `json:"input_invocation"`
		Diagnostics []tszCapturedDiagnostic `json:"diagnostics"`
		Outputs     []tszInputFile          `json:"outputs"`
		Emit        any                     `json:"emit"`
		Trace       string                  `json:"trace"`
	}{1, invocation, tszCaptureDiagnostics(t, directory, result.Diagnostics), outputs, emit, result.Trace}
	data, err := json.Marshal(record)
	if err != nil {
		t.Fatal(err)
	}
	tszWriteInput(t, filepath.Join(directory, "invocations", invocation+".json"), data)
}
