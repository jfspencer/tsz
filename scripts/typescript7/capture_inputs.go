// Reporting-only overlay at the native compiler harness's virtual filesystem
// boundary. No source, option, root selection, or oracle result is changed.
package harnessutil

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"runtime/debug"
	"sort"
	"strings"
	"sync"
	"testing"
	"testing/fstest"

	"github.com/microsoft/typescript-go/internal/bundled"
	"github.com/microsoft/typescript-go/internal/core"
	"github.com/microsoft/typescript-go/internal/tsoptions"
)

var tszInputCapture = struct {
	sync.Mutex
	sequence map[string]int
}{sequence: make(map[string]int)}

type tszInputFile struct {
	Path       string `json:"path"`
	Mode       uint32 `json:"mode"`
	ByteLength int    `json:"byte_length"`
	SHA256     string `json:"sha256"`
}

// Store byte blobs separately so shared test libraries are not duplicated for
// every case. A symlink's blob is its target path, as in the native MapFS.
func tszStoreInput(t *testing.T, directory, name string, file *fstest.MapFile) tszInputFile {
	t.Helper()
	hash := sha256.Sum256(file.Data)
	id := hex.EncodeToString(hash[:])
	tszWriteInput(t, filepath.Join(directory, "blobs", id), file.Data)
	return tszInputFile{name, uint32(file.Mode), len(file.Data), id}
}

func tszWriteInput(t *testing.T, path string, data []byte) {
	t.Helper()
	if previous, err := os.ReadFile(path); err == nil {
		if !bytes.Equal(previous, data) {
			t.Fatalf("conflicting captured input at %s", path)
		}
		return
	} else if !os.IsNotExist(err) {
		t.Fatal(err)
	}
	// Go runs multiple test packages in separate processes. Publish a complete
	// blob atomically so another package cannot read a partially written file.
	file, err := os.CreateTemp(filepath.Dir(path), ".capture-*")
	if err != nil {
		t.Fatal(err)
	}
	defer os.Remove(file.Name())
	defer file.Close()
	if _, err := file.Write(data); err != nil {
		t.Fatal(err)
	}
	if err := file.Close(); err != nil {
		t.Fatal(err)
	}
	if err := os.Link(file.Name(), path); err == nil {
		return
	} else if !os.IsExist(err) {
		t.Fatal(err)
	}
	previous, err := os.ReadFile(path)
	if err != nil || !bytes.Equal(previous, data) {
		t.Fatalf("conflicting captured input at %s: %v", path, err)
	}
}

func tszCaptureCompilation(
	t *testing.T,
	files map[string]any,
	roots []string,
	options *core.CompilerOptions,
	harness *HarnessOptions,
	currentDirectory string,
	config *tsoptions.ParsedCommandLine,
) {
	t.Helper()
	directory := os.Getenv("TSZ_ORACLE_INPUT_DIR")
	if directory == "" {
		t.Fatal("missing TSZ_ORACLE_INPUT_DIR")
	}
	build, ok := debug.ReadBuildInfo()
	if !ok || !strings.HasSuffix(build.Path, ".test") {
		t.Fatal("cannot identify native test package")
	}
	packageName := strings.TrimSuffix(build.Path, ".test")
	tszInputCapture.Lock()
	defer tszInputCapture.Unlock()
	for _, child := range []string{"blobs", "invocations"} {
		if err := os.MkdirAll(filepath.Join(directory, child), 0o755); err != nil {
			t.Fatal(err)
		}
	}
	entries := make([]tszInputFile, 0, len(files))
	for name, value := range files {
		file, ok := value.(*fstest.MapFile)
		if !ok {
			t.Fatalf("unhandled native filesystem entry %s: %T", name, value)
		}
		entries = append(entries, tszStoreInput(t, directory, name, file))
	}
	sort.Slice(entries, func(i, j int) bool { return entries[i].Path < entries[j].Path })
	var configSource *tszInputFile
	var extendedSources []string
	if config != nil && config.ConfigFile != nil {
		if source := config.ConfigFile.SourceFile; source != nil {
			entry := tszStoreInput(t, directory, source.FileName(), &fstest.MapFile{Data: []byte(source.Text())})
			configSource = &entry
		}
		extendedSources = config.ConfigFile.ExtendedSourceFiles
	}
	sequence := tszInputCapture.sequence[t.Name()]
	tszInputCapture.sequence[t.Name()]++
	record := struct {
		Schema           int                   `json:"schema"`
		Package          string                `json:"package"`
		Test             string                `json:"test"`
		Sequence         int                   `json:"sequence"`
		CurrentDirectory string                `json:"current_directory"`
		DefaultLibrary   string                `json:"default_library_path"`
		Roots            []string              `json:"roots"`
		Files            []tszInputFile        `json:"files"`
		Options          *core.CompilerOptions `json:"native_compiler_options"`
		Harness          *HarnessOptions       `json:"native_harness_options"`
		ConfigSource     *tszInputFile         `json:"config_source"`
		ExtendedSources  []string              `json:"extended_config_paths"`
	}{1, packageName, t.Name(), sequence, currentDirectory, bundled.LibPath(), roots, entries, options, harness, configSource, extendedSources}
	data, err := json.Marshal(record)
	if err != nil {
		t.Fatal(err)
	}
	key := sha256.Sum256([]byte(fmt.Sprintf("%s\x00%s\x00%d", packageName, t.Name(), sequence)))
	tszWriteInput(t, filepath.Join(directory, "invocations", hex.EncodeToString(key[:])+".json"), data)
}
