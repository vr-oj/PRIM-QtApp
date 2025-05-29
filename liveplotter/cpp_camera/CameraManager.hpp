// CameraManager.hpp
#pragma once

#include <string>
#include <vector>
#include <memory>

class CameraManager
{
public:
    CameraManager();
    ~CameraManager();

    bool initialize(const std::string &model_hint = "");
    void shutdown();

    std::vector<std::string> list_formats();
    std::vector<uint8_t> get_frame(int &width, int &height, int &channels);

private:
    class Impl;
    std::unique_ptr<Impl> impl;
};
