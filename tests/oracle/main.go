// Command oracle generates and evaluates a differential corpus for
// Masterminds/semver v3.5.0 and hashicorp/go-version v1.9.0.
//
//	go run . gen -out DIR [-seed N] [-n CONSTRAINTS] [-pool VERSIONS]
//
// It writes DIR/masterminds.jsonl.gz and DIR/hashicorp.jsonl.gz. See the
// README.txt shipped beside the committed fixture for the record format.
package main

import (
	"bufio"
	"compress/gzip"
	"encoding/json"
	"flag"
	"fmt"
	"math/rand/v2"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"github.com/Masterminds/semver/v3"
	hv "github.com/hashicorp/go-version"
)

type gen struct {
	r *rand.Rand
}

func (g *gen) pick(xs ...string) string { return xs[g.r.IntN(len(xs))] }
func (g *gen) chance(p float64) bool    { return g.r.Float64() < p }
func (g *gen) num() string {
	return g.pick("0", "0", "1", "1", "2", "3", "10")
}

const mutChars = ".-+vV_ x*|\t~é0,=<>!^\n"

func (g *gen) mutate(s string) string {
	rs := []rune(s)
	switch g.r.IntN(7) {
	case 0: // insert
		p := g.r.IntN(len(rs) + 1)
		c := []rune(mutChars)[g.r.IntN(len([]rune(mutChars)))]
		rs = append(rs[:p], append([]rune{c}, rs[p:]...)...)
	case 1: // delete
		if len(rs) > 0 {
			p := g.r.IntN(len(rs))
			rs = append(rs[:p], rs[p+1:]...)
		}
	case 2: // replace
		if len(rs) > 0 {
			rs[g.r.IntN(len(rs))] = []rune(mutChars)[g.r.IntN(len([]rune(mutChars)))]
		}
	case 3: // big number
		return s + g.pick(".18446744073709551616", ".18446744073709551615", ".9223372036854775808", ".9223372036854775807", ".99999999999999999999999")
	case 4: // leading zeros
		return g.pick("0", "00", "01") + s
	case 5:
		return s + g.pick(".", "..", ".0.0.0", "-", "+", "-.", "+.", "-a..b")
	case 6:
		return g.pick(" ", "\t", "  ") + s + g.pick(" ", "\n", "")
	}
	return string(rs)
}

// ---------- Masterminds ----------

func (g *gen) msvVersion(mut float64) string {
	k := g.r.Float64()
	s := g.num() + "." + g.num() + "." + g.num()
	if k < .12 {
		s = g.num() + "." + g.num()
	} else if k < .17 {
		s = g.num()
	}
	if g.chance(.25) {
		s += "-" + g.pick("alpha", "beta.1", "rc.1", "alpha.1", "0", "1", "rc.2", "x", "SNAPSHOT", "1.2", "a-b", "01", "beta.01", "0.0", "2.a")
	}
	if g.chance(.06) {
		s += "+" + g.pick("build.5", "b", "001", "a.b-c")
	}
	if g.chance(.1) {
		s = "v" + s
	}
	if g.chance(mut) {
		s = g.mutate(s)
	}
	return s
}

func (g *gen) msvWild() string {
	a := g.pick("0", "1", "2", "3")
	b := g.pick("0", "1", "2")
	return g.pick("*", "x", "X", a+".x", a+".*", a+"."+b+".x", a+"."+b+".*", a+".X.X", a+".x.x", a+".*.*", "x.1", "1.x.3", "x-rc.1", a+".x-beta")
}

var msvOps = []string{"", "=", "==", "!=", ">", ">=", "<", "<=", "~", "~>", "^", "=>", "=<", "<>", ">>", "==="}

func (g *gen) msvOne() string {
	k := g.r.Float64()
	if k < .12 {
		return g.msvWild()
	}
	if k < .2 {
		return g.msvVersion(.02) + g.pick(" - ", " - ", " -  ", "  -  ", "-", " -") + g.msvVersion(.02)
	}
	var o string
	if g.chance(.95) {
		o = msvOps[g.r.IntN(12)]
	} else {
		o = msvOps[g.r.IntN(len(msvOps))]
	}
	v := g.msvVersion(.02)
	if g.chance(.15) {
		v = g.msvWild()
	}
	return o + g.pick("", " ", "", "  ") + v
}

func (g *gen) msvConstraint() string {
	n := g.pick("1", "1", "1", "2", "2", "3")[0] - '0'
	parts := make([]string, n)
	for i := range parts {
		parts[i] = g.msvOne()
	}
	s := strings.Join(parts, g.pick(",", " ", ", ", " , ", "\t", ",  "))
	if g.chance(.25) {
		s += g.pick(" || ", "||", " ||", "|| ") + g.msvOne()
		if g.chance(.15) {
			s += " || " + g.msvOne()
		}
	}
	if g.chance(.03) {
		s = " " + s + " "
	}
	if g.chance(.03) {
		s = g.pick("", "||", "1.2.3 ||", ">=", "~", "^ ", ">1.0 <", ">= 1.2.3, <", "||||", ",", "1 2 ,", "> = 1", "1.2.3 - ", " - 1.2.3", ">=1.2.3,,<2", "*|*", "1|2", "|")
	}
	if g.chance(.08) {
		s = g.mutate(s)
	}
	return s
}

func q(err error) string {
	if err == nil {
		return ""
	}
	return err.Error()
}

type vrec map[string]any

func msvVersionRec(s string) (rec vrec, v *semver.Version) {
	rec = vrec{"t": "version", "v": s}
	func() {
		defer func() {
			if x := recover(); x != nil {
				rec["panic"] = fmt.Sprint(x)
			}
		}()
		var err error
		v, err = semver.NewVersion(s)
		if err != nil {
			rec["ok"] = false
			rec["err"] = err.Error()
			v = nil
		} else {
			rec["ok"] = true
			rec["str"] = v.String()
			rec["orig"] = v.Original()
			rec["maj"] = fmt.Sprint(v.Major())
			rec["min"] = fmt.Sprint(v.Minor())
			rec["pat"] = fmt.Sprint(v.Patch())
			rec["pre"] = v.Prerelease()
			rec["meta"] = v.Metadata()
		}
		sv, serr := semver.StrictNewVersion(s)
		if serr != nil {
			rec["sok"] = false
			rec["serr"] = serr.Error()
		} else {
			rec["sok"] = true
			rec["sstr"] = sv.String()
			rec["sorig"] = sv.Original()
		}
	}()
	return
}

func chkChar(b bool) byte {
	if b {
		return '1'
	}
	return '0'
}

func genMasterminds(g *gen, n, poolN int, w *json.Encoder) {
	w.Encode(map[string]any{"t": "meta", "dialect": "masterminds", "oracle": "github.com/Masterminds/semver/v3 v3.5.0", "constraints": n, "versions": poolN})
	pool := make([]*semver.Version, 0, poolN)
	fixed := []string{"1.2.3", "1.2.3-alpha", "0.0.0", "2.0.0", "1.9.9", "1.2.3-rc.1", "1.2.4", "1.3.0", "1.2.0", "v1.2.3", "1.2", "1", "1.2.3+build.1", "1.2.3-beta.1", "0.0.3", "0.2.3", "3.0.0-0", "2.0.0-alpha", "1.10.0", "18446744073709551615.0.0"}
	vs := append([]string{}, fixed...)
	for len(vs) < poolN {
		vs = append(vs, g.msvVersion(.12))
	}
	for _, s := range vs {
		rec, v := msvVersionRec(s)
		w.Encode(rec)
		pool = append(pool, v)
	}
	var valid []int
	for i, v := range pool {
		if v != nil {
			valid = append(valid, i)
		}
	}
	fixedC := []string{">=1.2.3", "~1.2.3", "^1.2.3", "^0.2.3", "^0.0.3", "~1.2", "~1", "^0", "^0.0", "1.2.x", ">=1.2.3-0", ">1.2.3-alpha", "*", "", ">=1.2.3 <2.0.0", ">=1.2.3, <2.0.0", "1.2.3 - 2.3.4", "~> 1.2", "~>1.2.3", "!=1.2.3", ">= 1.2.3-rc <1.3.0", "^1.2.3-beta.2", "1.x || 2.x", ">=1.0.0 <1.0.0 || >2", "=1.2.3", "v1.2.3", "1.2.3", "1", "1.2", ">1", ">1.2", "<1", "<=1", "<=1.2", ">=1.2", "!=1", "!=1.2", "~0", "~0.0", "~0.0.0", "^0.0.0", ">=0", "!=1.x", "!=1.2.x", "1.2.x-alpha", ">1.2.x", "<=1.x"}
	cs := append([]string{}, fixedC...)
	for len(cs) < n {
		cs = append(cs, g.msvConstraint())
	}
	for _, c := range cs {
		rec := map[string]any{"t": "constraint", "c": c}
		func() {
			defer func() {
				if x := recover(); x != nil {
					rec["panic"] = fmt.Sprint(x)
				}
			}()
			con, err := semver.NewConstraint(c)
			if err != nil {
				rec["ok"] = false
				rec["err"] = err.Error()
				return
			}
			rec["ok"] = true
			rec["str"] = con.String()
			k := 8
			vi := make([]int, 0, k)
			chk := make([]byte, 0, k)
			inc := make([]byte, 0, k)
			val := make([]any, 0, k)
			for j := 0; j < k; j++ {
				i := g.r.IntN(len(pool))
				vi = append(vi, i)
				v := pool[i]
				if v == nil {
					chk = append(chk, 'x')
					inc = append(inc, 'x')
					val = append(val, nil)
					continue
				}
				chk = append(chk, chkChar(con.Check(v)))
				ok, errs := con.Validate(v)
				parts := make([]string, len(errs))
				for x, e := range errs {
					parts[x] = e.Error()
				}
				if ok {
					val = append(val, "")
				} else {
					val = append(val, strings.Join(parts, "\n"))
				}
				c2 := *con
				c2.IncludePrerelease = true
				inc = append(inc, chkChar(c2.Check(v)))
				_ = ok
			}
			rec["vi"] = vi
			rec["chk"] = string(chk)
			rec["inc"] = string(inc)
			rec["val"] = val
			// IncludePrerelease Validate reasons for the first valid version.
			c3 := *con
			c3.IncludePrerelease = true
			ivs := make([]any, 0, k)
			for _, i := range vi {
				if pool[i] == nil {
					ivs = append(ivs, nil)
					continue
				}
				ok, errs := c3.Validate(pool[i])
				parts := make([]string, len(errs))
				for x, e := range errs {
					parts[x] = e.Error()
				}
				if ok {
					ivs = append(ivs, "")
				} else {
					ivs = append(ivs, strings.Join(parts, "\n"))
				}
			}
			rec["ival"] = ivs
		}()
		w.Encode(rec)
	}
	// compare + sort
	for i := 0; i < poolN*4; i++ {
		a, b := valid[g.r.IntN(len(valid))], valid[g.r.IntN(len(valid))]
		w.Encode(map[string]any{"t": "cmp", "a": a, "b": b, "r": pool[a].Compare(pool[b]), "eq": pool[a].Equal(pool[b])})
	}
	for i := 0; i < 3000; i++ {
		k := 2 + g.r.IntN(19)
		in := make([]int, k)
		for j := range in {
			in[j] = valid[g.r.IntN(len(valid))]
		}
		col := make(semver.Collection, k)
		idx := append([]int{}, in...)
		for j, x := range in {
			col[j] = pool[x]
		}
		sort.Stable(&byIdx{col, idx})
		w.Encode(map[string]any{"t": "sort", "in": in, "out": idx})
	}
}

type byIdx struct {
	c   semver.Collection
	idx []int
}

func (b *byIdx) Len() int           { return len(b.c) }
func (b *byIdx) Less(i, j int) bool { return b.c[i].LessThan(b.c[j]) }
func (b *byIdx) Swap(i, j int) {
	b.c[i], b.c[j] = b.c[j], b.c[i]
	b.idx[i], b.idx[j] = b.idx[j], b.idx[i]
}

// ---------- hashicorp ----------

func (g *gen) hvVersion(mut float64) string {
	segs := g.pick("1", "2", "3", "3", "3", "3", "4", "5")[0] - '0'
	parts := make([]string, segs)
	for i := range parts {
		parts[i] = g.num()
	}
	s := strings.Join(parts, ".")
	if g.chance(.22) {
		p := g.pick("beta", "rc1", "alpha", "beta1", "rc.1", "alpha.2", "1", "0", "~x", "a-b", "x.y", "1a", "1.a", "SNAPSHOT", "01", "a_b")
		s += g.pick("-", "-", "-", "") + p
	}
	if g.chance(.06) {
		s += "+" + g.pick("build.5", "b", "001", "a.b-c", "~", "meta")
	}
	if g.chance(.1) {
		s = "v" + s
	}
	if g.chance(mut) {
		s = g.mutate(s)
	}
	return s
}

var hvOps = []string{"", "=", "!=", ">", ">=", "<", "<=", "~>", "~>", "~>", "==", "=>", "=<", "~", ">>", "^", "<>"}

func (g *gen) hvOne() string {
	var o string
	if g.chance(.95) {
		o = hvOps[g.r.IntN(9)]
	} else {
		o = hvOps[g.r.IntN(len(hvOps))]
	}
	v := g.hvVersion(.02)
	if g.chance(.3) {
		// short constraint versions are the interesting ~> cases
		v = strings.Join([]string{g.num(), g.num(), g.num()}[:1+g.r.IntN(3)], ".")
		if g.chance(.15) {
			v += g.pick("-beta", "-rc1", "-alpha", "beta", "-1")
		}
	}
	return o + g.pick("", " ", "", "  ", "\t") + v
}

func (g *gen) hvConstraint() string {
	n := g.pick("1", "1", "2", "2", "3", "4")[0] - '0'
	parts := make([]string, n)
	for i := range parts {
		parts[i] = g.hvOne()
	}
	s := strings.Join(parts, g.pick(", ", ",", " , ", ",  ", ",\t"))
	if g.chance(.03) {
		s = " " + s + " "
	}
	if g.chance(.04) {
		s = g.pick("", ",", ">= 1.0,", ",>=1", ">=", "~>", "1.0 2.0", ">= 1.0 < 2.0", ">=1,,<2", "~> ", "|| 1", "1 || 2", ">=1.0.0-", "v", ">=v1", ">= v1.0")
	}
	if g.chance(.08) {
		s = g.mutate(s)
	}
	return s
}

func hvVersionRec(s string) (rec vrec, v *hv.Version) {
	rec = vrec{"t": "version", "v": s}
	func() {
		defer func() {
			if x := recover(); x != nil {
				rec["panic"] = fmt.Sprint(x)
			}
		}()
		var err error
		v, err = hv.NewVersion(s)
		if err != nil {
			rec["ok"] = false
			rec["err"] = err.Error()
			v = nil
		} else {
			rec["ok"] = true
			rec["str"] = v.String()
			rec["orig"] = v.Original()
			seg := []string{}
			for _, x := range v.Segments64() {
				seg = append(seg, fmt.Sprint(x))
			}
			rec["seg"] = seg
			rec["pre"] = v.Prerelease()
			rec["meta"] = v.Metadata()
			rec["core"] = v.Core().String()
		}
		sv, serr := hv.NewSemver(s)
		if serr != nil {
			rec["sok"] = false
			rec["serr"] = serr.Error()
		} else {
			rec["sok"] = true
			rec["sstr"] = sv.String()
		}
	}()
	return
}

func genHashicorp(g *gen, n, poolN int, w *json.Encoder) {
	w.Encode(map[string]any{"t": "meta", "dialect": "hashicorp", "oracle": "github.com/hashicorp/go-version v1.9.0", "constraints": n, "versions": poolN})
	fixed := []string{"1.2.3", "1.2.3-beta", "0.0.0", "2.0.0", "1.9.9", "1.2.3-rc1", "1.2.4", "1.3.0", "1.2.0", "v1.2.3", "1.2", "1", "1.2.3+build.1", "1.2.3.4", "1.2.3.0", "1.2.0.0", "1.0beta", "1.0-beta1", "2.0.0-alpha", "1.10.0", "9223372036854775807", "9223372036854775808"}
	vs := append([]string{}, fixed...)
	for len(vs) < poolN {
		vs = append(vs, g.hvVersion(.12))
	}
	pool := make([]*hv.Version, 0, poolN)
	for _, s := range vs {
		rec, v := hvVersionRec(s)
		w.Encode(rec)
		pool = append(pool, v)
	}
	var valid []int
	for i, v := range pool {
		if v != nil {
			valid = append(valid, i)
		}
	}
	fixedC := []string{"~> 1.2", "~> 1.2.0", "~> 1.2.3", "~> 1", "~> 1.0", "~> 0.12", "~> 1.2.3.4", "~>1.2-beta", ">= 1.0, < 2.0", ">= 1.0.0-beta", "> 1.0.0-beta, < 2", "= 1.0", "1.0", "!= 1.2.3", "<= 1.2", "", ">=1.2.3,<2.0.0", "~> 1.0-rc1", "~> 1.2.3-beta", "< 1.0.0-beta", "1.2.3-beta", "!= 1.2.3-beta", " >= 1.0 , < 2 "}
	cs := append([]string{}, fixedC...)
	for len(cs) < n {
		cs = append(cs, g.hvConstraint())
	}
	for _, c := range cs {
		rec := map[string]any{"t": "constraint", "c": c}
		func() {
			defer func() {
				if x := recover(); x != nil {
					rec["panic"] = fmt.Sprint(x)
				}
			}()
			con, err := hv.NewConstraint(c)
			if err != nil {
				rec["ok"] = false
				rec["err"] = err.Error()
				return
			}
			rec["ok"] = true
			rec["str"] = con.String()
			sorted := append(hv.Constraints{}, con...)
			sort.Stable(sorted)
			rec["srt"] = sorted.String()
			k := 8
			vi := make([]int, 0, k)
			chk := make([]byte, 0, k)
			for j := 0; j < k; j++ {
				i := g.r.IntN(len(pool))
				vi = append(vi, i)
				if pool[i] == nil {
					chk = append(chk, 'x')
				} else {
					chk = append(chk, chkChar(con.Check(pool[i])))
				}
			}
			rec["vi"] = vi
			rec["chk"] = string(chk)
		}()
		w.Encode(rec)
	}
	for i := 0; i < poolN*4; i++ {
		a, b := valid[g.r.IntN(len(valid))], valid[g.r.IntN(len(valid))]
		w.Encode(map[string]any{"t": "cmp", "a": a, "b": b, "r": pool[a].Compare(pool[b]), "eq": pool[a].Equal(pool[b])})
	}
	for i := 0; i < 3000; i++ {
		k := 2 + g.r.IntN(19)
		in := make([]int, k)
		for j := range in {
			in[j] = valid[g.r.IntN(len(valid))]
		}
		col := make(hv.Collection, k)
		idx := append([]int{}, in...)
		for j, x := range in {
			col[j] = pool[x]
		}
		sort.Stable(&hvByIdx{col, idx})
		w.Encode(map[string]any{"t": "sort", "in": in, "out": idx})
	}
}

type hvByIdx struct {
	c   hv.Collection
	idx []int
}

func (b *hvByIdx) Len() int           { return len(b.c) }
func (b *hvByIdx) Less(i, j int) bool { return b.c[i].LessThan(b.c[j]) }
func (b *hvByIdx) Swap(i, j int) {
	b.c[i], b.c[j] = b.c[j], b.c[i]
	b.idx[i], b.idx[j] = b.idx[j], b.idx[i]
}

func write(path string, f func(*json.Encoder)) {
	fh, err := os.Create(path)
	if err != nil {
		panic(err)
	}
	// Fixed header fields keep the gzip output reproducible.
	zw, _ := gzip.NewWriterLevel(fh, gzip.BestCompression)
	bw := bufio.NewWriter(zw)
	enc := json.NewEncoder(bw)
	enc.SetEscapeHTML(false)
	f(enc)
	bw.Flush()
	zw.Close()
	fh.Close()
}

func main() {
	if len(os.Args) >= 2 && os.Args[1] == "probe" {
		probeMain(os.Args[2:])
		return
	}
	if len(os.Args) < 2 || os.Args[1] != "gen" {
		fmt.Fprintln(os.Stderr, "usage: oracle gen -out DIR [-seed N] [-n N] [-pool N]\n       oracle probe -in FILE -out FILE")
		os.Exit(2)
	}
	fs := flag.NewFlagSet("gen", flag.ExitOnError)
	out := fs.String("out", "", "output directory")
	seed := fs.Uint64("seed", 1, "PRNG seed")
	n := fs.Int("n", 20000, "constraints per dialect")
	pool := fs.Int("pool", 600, "versions per dialect")
	fs.Parse(os.Args[2:])
	if *out == "" {
		fs.Usage()
		os.Exit(2)
	}
	os.MkdirAll(*out, 0o755)
	write(filepath.Join(*out, "masterminds.jsonl.gz"), func(e *json.Encoder) {
		genMasterminds(&gen{rand.New(rand.NewPCG(*seed, 1))}, *n, *pool, e)
	})
	write(filepath.Join(*out, "hashicorp.jsonl.gz"), func(e *json.Encoder) {
		genHashicorp(&gen{rand.New(rand.NewPCG(*seed, 2))}, *n, *pool, e)
	})
}
