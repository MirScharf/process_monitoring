#include <chrono>
#include <cmath>
#include <iostream>
#include <thread>

int main() {
    std::cout << "C++ demo process started. Press Ctrl+C to stop." << std::endl;

    while (true) {
        volatile double acc = 0.0;
        auto start = std::chrono::steady_clock::now();
        while (std::chrono::steady_clock::now() - start < std::chrono::milliseconds(800)) {
            acc += std::sqrt(12345.6789);
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(200));
    }

    return 0;
}
