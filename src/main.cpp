#include "internal.hpp"
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>

namespace {
bool line(std::istream& in,std::string& text,bool& too_large) {
    text.clear(); too_large=false; char c=0; bool any=false;
    while (in.get(c)) { any=true; if (c=='\n') break; if (text.size()<jarvis::kMaxRequestBytes) text+=c; else too_large=true; }
    if (!text.empty()&&text.back()=='\r') text.pop_back(); return any;
}
}
int wmain(int argc,wchar_t** argv) {
    try {
        jarvis::Json config=jarvis::Json::object(); std::string request; bool single=false,enable=false;
        for (int i=1;i<argc;++i) {
            const std::string arg=jarvis::utf8(argv[i]);
            if (arg=="--help") { std::cout<<"jarvis-core [--stdio] [--request JSON] [--config FILE] [--enable-actions]\n"; return 0; }
            if (arg=="--version") { std::cout<<jarvis::kVersion<<'\n'; return 0; }
            if (arg=="--enable-actions") enable=true;
            else if (arg=="--stdio") {}
            else if (arg=="--request"&&i+1<argc) { request=jarvis::utf8(argv[++i]); single=true; }
            else if (arg=="--config"&&i+1<argc) {
                std::ifstream file(std::filesystem::path(argv[++i]),std::ios::binary);
                if (!file) throw std::runtime_error("Cannot open configuration file");
                file.seekg(0,std::ios::end); const auto size=file.tellg();
                if (size<0||size>static_cast<std::streamoff>(jarvis::kMaxRequestBytes)) throw std::runtime_error("Configuration too large");
                file.seekg(0); config=jarvis::Json::parse(file);
            } else throw std::runtime_error("Unknown argument or missing value: "+arg);
        }
        if (enable) config["enable_actions"]=true;
        jarvis::Kernel kernel(config);
        const auto emit=[&](const std::string& input) { const auto response=kernel.execute(input); std::cout<<response.dump(-1,' ',true)<<'\n'<<std::flush; return response.at("ok").get<bool>(); };
        if (single) return emit(request)?0:2;
        bool too_large=false;
        while (line(std::cin,request,too_large)) emit(too_large?std::string(jarvis::kMaxRequestBytes+1,' '):request);
        return 0;
    } catch (const std::exception& e) { std::cerr<<"jarvis-core: "<<e.what()<<'\n'; return 1; }
}
