// Driver for AutoPipeline's `kernel` self-intersection backend (kit/selfcross.py, `python -m kit selfcross build`).
//
// It runs villa's census kernel, volume-cartographer/apps/src/vc_tifxyz_selfcross_impl.hpp, on a raw float32
// (rows, cols, 3) grid that kit/selfcross.py has already loaded the way VC3D loads a tifxyz (z <= 0 cells and cells
// mask.tif rejects set to -1). The header is fetched at build time at a pinned villa commit and checked by sha256;
// it is never copied into this repository. villa's code is GPL-3.0, so the binary built from it is too: it stays on
// the machine that built it. This file is ours (Apache-2.0).
//
// Usage: selfcross_kernel GRID.f32 ROWS COLS OUT.json [--exclude N] [--maxedge V] [--cell V] [--threads N]
// Writes {"grid_rows", "grid_cols", "census": [...]}, the census rows of villa's vc_tifxyz_selfcross report for
// diagonals 0 and 1; kit/selfcross.py writes the rest of the report around them.
// Exit codes: 0 the census ran, 1 an error (bad arguments, unreadable grid, a parameter the kernel refuses).
#include "vc_tifxyz_selfcross_impl.hpp"

#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>

using namespace vc_selfcross;

static std::string num(double v) {
    char b[64];
    std::snprintf(b, sizeof b, "%.17g", v);
    return b;
}

int main(int argc, char** argv) {
    if (argc < 5 || (argc - 5) % 2) {
        std::cerr << "usage: selfcross_kernel GRID.f32 ROWS COLS OUT.json [--exclude N] [--maxedge V] [--cell V] "
                     "[--threads N]\n";
        return 1;
    }
    const long rows = std::atol(argv[2]), cols = std::atol(argv[3]);
    if (rows < 0 || cols < 0) { std::cerr << "Error: ROWS and COLS are 0 or more\n"; return 1; }
    int exclude = 1, threads = 0;
    double maxedge = 60.0, cell = 40.0;
    for (int i = 5; i + 1 < argc; i += 2) {
        const std::string k = argv[i];
        const char* v = argv[i + 1];
        if (k == "--exclude") exclude = std::atoi(v);
        else if (k == "--maxedge") maxedge = std::atof(v);
        else if (k == "--cell") cell = std::atof(v);
        else if (k == "--threads") threads = std::atoi(v);
        else { std::cerr << "Error: unknown option " << k << "\n"; return 1; }
    }
    cv::Mat_<cv::Vec3f> P((int)rows, (int)cols);
    const size_t n = (size_t)rows * (size_t)cols * 3;
    FILE* f = std::fopen(argv[1], "rb");
    if (!f) { std::cerr << "Error: cannot open " << argv[1] << "\n"; return 1; }
    const size_t got = n ? std::fread(P.ptr(0), sizeof(float), n, f) : 0;
    std::fclose(f);
    if (got != n) { std::cerr << "Error: " << argv[1] << " holds fewer than ROWS x COLS x 3 floats\n"; return 1; }

    std::vector<Contact> contacts[2];
    CensusCounts counts[2];
    for (int d = 0; d < 2; ++d) {
        try {
            counts[d] = census(P, d, cell, exclude, maxedge, threads, contacts[d]);
        } catch (const std::invalid_argument& e) {
            std::cerr << "Error: " << e.what() << "\n";
            return 1;
        }
        std::cerr << "diagonal " << d << ": " << counts[d].triangles << " triangles, " << counts[d].pairs_tested
                  << " pairs tested, " << counts[d].transverse << " transverse, " << counts[d].coplanar
                  << " coplanar, " << counts[d].grazing << " grazing\n";
    }
    std::ofstream o(argv[4]);
    if (!o.is_open()) { std::cerr << "Error: cannot write " << argv[4] << "\n"; return 1; }
    o << "{\"grid_rows\":" << rows << ",\"grid_cols\":" << cols << ",\"census\":[";
    for (int d = 0; d < 2; ++d) {
        const CensusCounts& k = counts[d];
        o << (d ? "," : "") << "{\"diagonal\":" << d << ",\"triangles\":" << k.triangles
          << ",\"quads_dropped_for_edge_length\":" << k.quads_dropped << ",\"pairs_tested\":" << k.pairs_tested
          << ",\"transverse\":" << k.transverse << ",\"coplanar\":" << k.coplanar << ",\"grazing\":" << k.grazing
          << ",\"transverse_contacts\":[";
        bool first = true;
        for (const Contact& c : contacts[d]) {
            if (c.verdict != TRANSVERSE) continue;
            o << (first ? "" : ",") << "{\"quad1\":[" << c.v1 << "," << c.u1 << "],\"quad2\":[" << c.v2 << ","
              << c.u2 << "],\"tri1\":" << c.t1 << ",\"tri2\":" << c.t2
              << ",\"penetration_vx\":" << num((double)c.penetration) << ",\"angle_deg\":" << num((double)c.angle_deg)
              << ",\"site\":[" << num(c.site.x) << "," << num(c.site.y) << "," << num(c.site.z) << "]}";
            first = false;
        }
        o << "]}";
    }
    o << "],\"touch_tolerance\":" << num(TOUCH_TOL) << "}";
    o.close();
    if (o.fail()) { std::cerr << "Error: failed while writing " << argv[4] << "\n"; return 1; }
    return 0;
}
