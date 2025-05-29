// CameraManager.cpp
#include "CameraManager.hpp"
#include <tisic4/tisic4.hpp>
#include <iostream>

class CameraManager::Impl
{
public:
    tisic4::Device device;
    std::shared_ptr<tisic4::Sink> sink;
    tisic4::Stream stream;
    tisic4::VideoFormat current_format;
    bool initialized = false;

    bool initialize(const std::string &model_hint)
    {
        auto devices = tisic4::enumerateDevices();
        for (const auto &d : devices)
        {
            if (model_hint.empty() || d.modelName().find(model_hint) != std::string::npos)
            {
                device = d.openDevice();
                auto formats = device.availableVideoFormats();
                if (formats.empty())
                {
                    std::cerr << "No video formats found!" << std::endl;
                    return false;
                }

                current_format = formats.front();
                device.setVideoFormat(current_format);

                sink = tisic4::createSink(tisic4::SinkType::SystemMemory);
                stream = device.createStream(sink);
                stream.start();

                initialized = true;
                return true;
            }
        }
        std::cerr << "No compatible device found.\n";
        return false;
    }

    void shutdown()
    {
        if (initialized)
        {
            stream.stop();
            device = tisic4::Device(); // release
            sink.reset();
            initialized = false;
        }
    }

    std::vector<std::string> list_formats()
    {
        std::vector<std::string> formats;
        for (const auto &fmt : device.availableVideoFormats())
        {
            formats.push_back(fmt.toString());
        }
        return formats;
    }

    std::vector<uint8_t> get_frame(int &width, int &height, int &channels)
    {
        if (!initialized || !sink)
            return {};

        auto buffer = sink->snap();
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
