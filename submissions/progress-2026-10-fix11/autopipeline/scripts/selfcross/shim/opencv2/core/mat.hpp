// A stand-in for the two OpenCV types villa's self-intersection census kernel uses: cv::Vec3f and cv::Mat_<T> with
// rows, cols, operator()(r, c), ptr and setTo. With it the kernel builds with a C++17 compiler alone, no OpenCV.
// Written for kit's selfcross driver (scripts/selfcross/selfcross_kernel.cpp); no OpenCV code. Apache-2.0.
#pragma once
#include <cstddef>
#include <vector>

namespace cv {
template <class T, int N> struct Vec {
    T val[N];
    Vec() { for (int i = 0; i < N; ++i) val[i] = T(0); }
    Vec(T a, T b, T c) { static_assert(N == 3, "3-vectors only"); val[0] = a; val[1] = b; val[2] = c; }
    T& operator[](int i) { return val[i]; }
    const T& operator[](int i) const { return val[i]; }
};
typedef Vec<float, 3> Vec3f;

template <class T> struct Mat_ {
    int rows = 0, cols = 0;
    std::vector<T> data;
    Mat_() = default;
    Mat_(int r, int c) : rows(r), cols(c), data(std::size_t(r) * std::size_t(c)) {}
    T& operator()(int r, int c) { return data[std::size_t(r) * cols + c]; }
    const T& operator()(int r, int c) const { return data[std::size_t(r) * cols + c]; }
    T* ptr(int r) { return data.data() + std::size_t(r) * cols; }
    const T* ptr(int r) const { return data.data() + std::size_t(r) * cols; }
    void setTo(const T& v) { for (auto& x : data) x = v; }
};
}  // namespace cv
