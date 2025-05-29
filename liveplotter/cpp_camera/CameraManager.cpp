// CameraManager.cpp
#include "CameraManager.hpp"
#include <ic4/ic4.h>
#include <iostream>

class CameraManager::Impl
{
public:
    ic4::Device device;
    ic4::Sink sink;
    ic4::Stream stream;
    ic4::VideoFormat current_format;
    bool initialized = false;

    bool initialize(const std::string &model_hint)
    {
        auto devices = ic4::Device::enumerate();
        for (const auto &d : devices)
        {
            if (model_hint.empty() || d.modelName.find(model_hint) != std::string::npos)
            {
                device = d.open();
                current_format = device.videoFormats().front();
                device.setVideoFormat(current_format);
                sink = device.sink();
                stream = device.stream();
                stream.start();
                initialized = true;
                return true;
            }
        }
        return false;
    }

    void shutdown()
    {
        if (initialized)
        {
            stream.stop();
            device.close();
            initialized = false;
        }
    }

    std::vector<std::string> list_formats()
    {
        std::vector<std::string> formats;
        for (const auto &fmt : device.videoFormats())
        {
            formats.push_back(fmt.toString());
        }
        return formats;
    }

    std::vector<uint8_t> get_frame(int &width, int &height, int &channels)
    {
        if (!initialized)
            return {};
        auto buffer = sink.snap();
        width = buffer.width();
        height = buffer.height();
        channels = buffer.pixelFormat().numChannels();
        return std::vector<uint8_t>(buffer.data(), buffer.data() + buffer.size());
    }
};

CameraManager::CameraManager() : impl(std::make_unique<Impl>()) {}
CameraManager::~CameraManager() { impl->shutdown(); }
bool CameraManager::initialize(const std::string &model_hint) { return impl->initialize(model_hint); }
void CameraManager::shutdown() { impl->shutdown(); }
std::vector<std::string> CameraManager::list_formats() { return impl->list_formats(); }
std::vector<uint8_t> CameraManager::get_frame(int &width, int &height, int &channels) { return impl->get_frame(width, height, channels); }
