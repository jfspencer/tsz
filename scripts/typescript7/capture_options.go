// Native option declarations are transport metadata, never candidate answers.
package harnessutil

import (
	"encoding/json"
	"path/filepath"
	"testing"

	"github.com/microsoft/typescript-go/internal/tsoptions"
)

type tszOptionSchema struct {
	Name       string           `json:"name"`
	Kind       string           `json:"kind"`
	ConfigOnly bool             `json:"config_only"`
	FilePath   bool             `json:"file_path"`
	Enum       map[string]any   `json:"enum,omitempty"`
	Element    *tszOptionSchema `json:"element,omitempty"`
}

func tszDescribeOption(option *tsoptions.CommandLineOption) *tszOptionSchema {
	if option == nil {
		return nil
	}
	result := &tszOptionSchema{
		Name: option.Name, Kind: string(option.Kind), ConfigOnly: option.IsTSConfigOnly,
		FilePath: option.IsFilePath, Element: tszDescribeOption(option.Elements()),
	}
	if values := option.EnumMap(); values != nil {
		result.Enum = make(map[string]any, values.Size())
		for name, value := range values.Entries() {
			result.Enum[name] = value
		}
	}
	return result
}

func tszCaptureOptionSchema(t *testing.T, directory string) {
	t.Helper()
	options := make(map[string]*tszOptionSchema)
	for _, option := range tsoptions.OptionsDeclarations {
		options[option.Name] = tszDescribeOption(option)
	}
	data, err := json.Marshal(options)
	if err != nil {
		t.Fatal(err)
	}
	tszWriteInput(t, filepath.Join(directory, "options.json"), data)
}
