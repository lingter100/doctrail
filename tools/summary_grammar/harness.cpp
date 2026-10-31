// Model-free finite-corpus checker; APIs pinned to llama.cpp d81235049384534c167caea52b85a694f6103d14.
#include "llama-grammar.h"
#include "unicode.h"
#include <algorithm>
#include <chrono>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>

using Clock = std::chrono::steady_clock;
using Grammar = std::unique_ptr<llama_grammar, decltype(&llama_grammar_free_impl)>;
static Clock::time_point started;
static void need(bool ok, const char * message) { if (!ok) throw std::runtime_error(message); }
static double ms(Clock::time_point t) { return std::chrono::duration<double, std::milli>(Clock::now() - t).count(); }
static void deadline() { need(ms(started) < 55000.0, "shared_active_deadline"); }
static std::string read_binary(const char * file) {
    std::ifstream in(file, std::ios::binary);
    need(bool(in), "input_open");
    std::string data;
    char chunk[16384];
    while (in.read(chunk, sizeof(chunk)) || in.gcount()) {
        need(data.size() + size_t(in.gcount()) <= 2097152, "input_size");
        data.append(chunk, size_t(in.gcount()));
        deadline();
    }
    need(in.eof(), "input_read");
    return data;
}
// Reject malformed, overlong, surrogate and out-of-range carriers before the official conversion.
static void strict_utf8(const std::string & s) {
    for (size_t i = 0; i < s.size();) {
        uint32_t first = static_cast<unsigned char>(s[i++]), cp = first, n = 0, minimum = 0;
        if (first < 128) continue;
        if (first >= 0xc2 && first <= 0xdf) { n = 1; cp &= 31; minimum = 0x80; }
        else if (first >= 0xe0 && first <= 0xef) { n = 2; cp &= 15; minimum = 0x800; }
        else if (first >= 0xf0 && first <= 0xf4) { n = 3; cp &= 7; minimum = 0x10000; }
        else throw std::runtime_error("invalid_utf8");
        need(i + n <= s.size(), "incomplete_utf8");
        for (uint32_t j = 0; j < n; ++j) {
            uint32_t ch = static_cast<unsigned char>(s[i++]);
            need((ch & 0xc0) == 0x80, "invalid_utf8_continuation"); cp = (cp << 6) | (ch & 63);
        }
        need(cp >= minimum && cp <= 0x10ffff && !(cp >= 0xd800 && cp <= 0xdfff), "non_scalar_utf8");
    }
}
static uint32_t number(const std::string & s, size_t & pos) {
    need(pos + 4 <= s.size(), "truncated_batch"); uint32_t n = 0;
    for (int i = 0; i < 4; ++i) n |= uint32_t(static_cast<unsigned char>(s[pos++])) << (8 * i);
    return n;
}
static std::string field(const std::string & s, size_t & pos) {
    auto n = number(s, pos); need(n <= 2097152 && pos + n <= s.size(), "batch_length");
    auto result = s.substr(pos, n); pos += n; strict_utf8(result); return result;
}
static int state(llama_grammar * g) {
    auto & stacks = llama_grammar_get_stacks(g);
    if (stacks.empty()) return 0;
    for (const auto & stack : stacks) if (stack.empty()) return 2;
    return 1;
}
static void consume(llama_grammar * g, const std::string & bytes) {
    strict_utf8(bytes);
    for (auto cp : unicode_cpts_from_utf8(bytes)) {
        deadline();
        if (llama_grammar_get_stacks(g).empty()) break;
        llama_grammar_accept(g, cp);
    }
}
int main(int argc, char ** argv) {
    started = Clock::now();
    try {
        need(argc == 3, "usage_grammar_batch");
        auto grammar = read_binary(argv[1]), batch = read_binary(argv[2]);
        strict_utf8(grammar); need(grammar.find('\0') == std::string::npos, "grammar_nul");
        need(batch.substr(0, 4) == "SGE1", "protocol_magic");
        size_t pos = 4; auto count = number(batch, pos); need(count == 105, "native_count");
        auto init_start = Clock::now();
        Grammar initial(llama_grammar_init_impl(nullptr, grammar.c_str(), "root", false, nullptr, 0, nullptr, 0), llama_grammar_free_impl);
        need(bool(initial), "initialization_failed"); deadline();
        auto rules = llama_grammar_get_rules(initial.get()).size(); need(rules > 0 && rules <= 20000, "expanded_rules_limit");
        std::cout << "{\"init_ms\":" << ms(init_start) << ",\"rules\":" << rules << "}" << std::endl;
        double clone_total = 0, longest = 0;
        const char * names[] = {"dead", "prefix", "complete"};
        for (uint32_t i = 0; i < count; ++i) {
            deadline(); auto case_start = Clock::now(); auto expected = number(batch, pos);
            need(expected <= 2, "expected_state"); auto raw = field(batch, pos), suffix = field(batch, pos);
            need((expected == 1) == !suffix.empty(), "witness_required_only_for_prefix");
            auto clone_start = Clock::now(); Grammar current(llama_grammar_clone_impl(*initial), llama_grammar_free_impl);
            need(bool(current), "clone_failed"); double clone_ms = ms(clone_start); clone_total += clone_ms;
            consume(current.get(), raw); auto verdict = state(current.get()); int witness = -1;
            if (!suffix.empty()) { consume(current.get(), suffix); witness = state(current.get()); }
            current.reset(); double elapsed = ms(case_start); longest = std::max(longest, elapsed);
            std::cout << "{\"case\":" << i << ",\"state\":\"" << names[verdict] << "\",\"witness\":";
            if (witness < 0) std::cout << "null"; else std::cout << "\"" << names[witness] << "\"";
            std::cout << ",\"clone_ms\":" << clone_ms << ",\"elapsed_ms\":" << elapsed << "}" << std::endl;
            need(uint32_t(verdict) == expected && (witness < 0 || witness == 2), "verdict_mismatch");
        }
        need(pos == batch.size(), "trailing_batch"); initial.reset(); deadline();
        std::cout << "{\"done\":" << count << ",\"clone_total_ms\":" << clone_total << ",\"longest_ms\":" << longest << ",\"total_ms\":" << ms(started) << "}" << std::endl;
        return 0;
    } catch (const std::exception & e) { std::cerr << e.what() << std::endl; return 1; }
    catch (...) { std::cerr << "unknown_exception" << std::endl; return 1; }
}
