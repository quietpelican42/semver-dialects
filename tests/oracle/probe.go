package main

// probe answers ad-hoc questions about both libraries so tests can compare
// arbitrary inputs, not only the ones gen produced.
//
//	go run . probe -in requests.jsonl -out answers.jsonl
//
// One JSON request per line:
//
//	{"d":"masterminds"|"hashicorp","k":"version","v":"1.2.3"}
//	{"d":...,"k":"constraint","c":">=1.0","vs":["1.2.3","1.0.0-beta"]}
//	{"d":...,"k":"sort","pool":["1.0.0","2.0.0"],"in":[1,0]}
//
// Answers use the record shapes documented in the corpus README.

import (
	"bufio"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"sort"
	"strings"

	"github.com/Masterminds/semver/v3"
	hv "github.com/hashicorp/go-version"
)

type request struct {
	D    string   `json:"d"`
	K    string   `json:"k"`
	V    string   `json:"v"`
	C    string   `json:"c"`
	Vs   []string `json:"vs"`
	Pool []string `json:"pool"`
	In   []int    `json:"in"`
}

func reasons(errs []error, ok bool) string {
	if ok {
		return ""
	}
	parts := make([]string, len(errs))
	for i, e := range errs {
		parts[i] = e.Error()
	}
	return strings.Join(parts, "\n")
}

func probeMasterminds(r request) map[string]any {
	switch r.K {
	case "version":
		rec, _ := msvVersionRec(r.V)
		return rec
	case "constraint":
		rec := map[string]any{"t": "constraint", "c": r.C}
		con, err := semver.NewConstraint(r.C)
		if err != nil {
			rec["ok"] = false
			rec["err"] = err.Error()
			return rec
		}
		rec["ok"] = true
		rec["str"] = con.String()
		chk, inc := []byte{}, []byte{}
		val, ival := []any{}, []any{}
		c2 := *con
		c2.IncludePrerelease = true
		for _, s := range r.Vs {
			v, err := semver.NewVersion(s)
			if err != nil {
				chk, inc = append(chk, 'x'), append(inc, 'x')
				val, ival = append(val, nil), append(ival, nil)
				continue
			}
			chk = append(chk, chkChar(con.Check(v)))
			inc = append(inc, chkChar(c2.Check(v)))
			ok, errs := con.Validate(v)
			val = append(val, reasons(errs, ok))
			ok, errs = c2.Validate(v)
			ival = append(ival, reasons(errs, ok))
		}
		rec["chk"], rec["inc"], rec["val"], rec["ival"] = string(chk), string(inc), val, ival
		return rec
	case "sort":
		col := make(semver.Collection, len(r.In))
		idx := append([]int{}, r.In...)
		for j, x := range r.In {
			col[j] = semver.MustParse(r.Pool[x])
		}
		sort.Stable(&byIdx{col, idx})
		return map[string]any{"t": "sort", "out": idx}
	}
	return map[string]any{"error": "bad kind"}
}

func probeHashicorp(r request) map[string]any {
	switch r.K {
	case "version":
		rec, _ := hvVersionRec(r.V)
		return rec
	case "constraint":
		rec := map[string]any{"t": "constraint", "c": r.C}
		con, err := hv.NewConstraint(r.C)
		if err != nil {
			rec["ok"] = false
			rec["err"] = err.Error()
			return rec
		}
		rec["ok"] = true
		rec["str"] = con.String()
		sorted := append(hv.Constraints{}, con...)
		sort.Stable(sorted)
		rec["srt"] = sorted.String()
		chk := []byte{}
		for _, s := range r.Vs {
			v, err := hv.NewVersion(s)
			if err != nil {
				chk = append(chk, 'x')
				continue
			}
			chk = append(chk, chkChar(con.Check(v)))
		}
		rec["chk"] = string(chk)
		return rec
	case "sort":
		col := make(hv.Collection, len(r.In))
		idx := append([]int{}, r.In...)
		for j, x := range r.In {
			col[j] = hv.Must(hv.NewVersion(r.Pool[x]))
		}
		sort.Stable(&hvByIdx{col, idx})
		return map[string]any{"t": "sort", "out": idx}
	}
	return map[string]any{"error": "bad kind"}
}

func probeMain(args []string) {
	fs := flag.NewFlagSet("probe", flag.ExitOnError)
	in := fs.String("in", "", "requests file (JSON lines)")
	out := fs.String("out", "", "answers file (JSON lines)")
	fs.Parse(args)
	if *in == "" || *out == "" {
		fs.Usage()
		os.Exit(2)
	}
	fin, err := os.Open(*in)
	if err != nil {
		panic(err)
	}
	defer fin.Close()
	fout, err := os.Create(*out)
	if err != nil {
		panic(err)
	}
	defer fout.Close()
	bw := bufio.NewWriter(fout)
	enc := json.NewEncoder(bw)
	enc.SetEscapeHTML(false)
	sc := bufio.NewScanner(fin)
	sc.Buffer(make([]byte, 1<<20), 1<<26)
	for sc.Scan() {
		var r request
		if err := json.Unmarshal(sc.Bytes(), &r); err != nil {
			panic(fmt.Sprintf("bad request %q: %v", sc.Text(), err))
		}
		var rec map[string]any
		func() {
			defer func() {
				if x := recover(); x != nil {
					rec = map[string]any{"panic": fmt.Sprint(x)}
				}
			}()
			if r.D == "masterminds" {
				rec = probeMasterminds(r)
			} else {
				rec = probeHashicorp(r)
			}
		}()
		enc.Encode(rec)
	}
	bw.Flush()
}
