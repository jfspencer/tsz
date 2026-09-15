// Injected only for capture-contract tests, never into an oracle observation.
package harnessutil

import (
	"bytes"
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
