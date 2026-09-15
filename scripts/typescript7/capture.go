// Reporting-only overlay for the pinned upstream baseline package.
// The original comparison still runs, with the original actual bytes.
package baseline

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"sync"
	"testing"
)

var tszCaptureMu sync.Mutex

func tszCaptureBaseline(t *testing.T, name, actual string) {
	t.Helper()
	dir := os.Getenv("TSZ_ORACLE_CAPTURE_DIR")
	if dir == "" {
		t.Fatal("missing TSZ_ORACLE_CAPTURE_DIR")
	}
	// Include the product path: a single subtest can publish multiple products.
	key := t.Name() + "\x00" + filepath.ToSlash(name)
	id := sha256.Sum256([]byte(key))
	contentHash := sha256.Sum256([]byte(actual))
	record := struct {
		Test    string `json:"test"`
		Path    string `json:"path"`
		Absent  bool   `json:"absent"`
		SHA256  string `json:"sha256"`
		Content string `json:"content"`
	}{t.Name(), filepath.ToSlash(name), actual == NoContent, hex.EncodeToString(contentHash[:]), actual}
	data, err := json.Marshal(record)
	if err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(dir, hex.EncodeToString(id[:])+".json")
	tszCaptureMu.Lock()
	defer tszCaptureMu.Unlock()
	if previous, err := os.ReadFile(path); err == nil {
		if string(previous) != string(data) {
			t.Fatalf("conflicting oracle products for %q", key)
		}
		return
	} else if !os.IsNotExist(err) {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, data, 0o644); err != nil {
		t.Fatal(err)
	}
}
