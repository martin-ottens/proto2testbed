#include "ns3/core-module.h"
#include "ns3/csma-module.h"
#include "ns3/internet-module.h"
#include "ns3/ipv4-global-routing-helper.h"
#include "ns3/network-module.h"
#include "ns3/tap-bridge-module.h"

#include <string>

using namespace ns3;

NS_LOG_COMPONENT_DEFINE("Emulator");


int main(int argc, char* argv[]) {
    LogComponentEnable("Emulator", LOG_LEVEL_INFO);

    std::string mode = "UseBridge";
    std::string tapName0 = "ns3_em0";
    std::string tapName1 = "ns3_em1";
    uint16_t runSeconds = 100;
    uint64_t delayNanoSeconds = 50000;
    uint16_t noOfRouters = 1;

    CommandLine cmd(__FILE__);
    cmd.AddValue("runfor", "Simulation runtime seconds", runSeconds);
    cmd.AddValue("delay", "Link delay in nanoseconds", delayNanoSeconds);
    cmd.AddValue("routers", "Number of routers between OS tap devices", noOfRouters);
    cmd.Parse(argc, argv);

    if (noOfRouters == 0 || noOfRouters > 63) {
        NS_LOG_ERROR("Invalid router count");
        return 1;
    }

    GlobalValue::Bind("SimulatorImplementationType", StringValue("ns3::RealtimeSimulatorImpl"));
    GlobalValue::Bind("ChecksumEnabled", BooleanValue(true));
    Config::SetDefault("ns3::RealtimeSimulatorImpl::SynchronizationMode", StringValue("BestEffort"));

    NodeContainer nodes;
    nodes.Create(2 + noOfRouters);

    CsmaHelper csma;
    csma.SetChannelAttribute("DataRate", StringValue("1000Mbps"));
    csma.SetChannelAttribute("Delay", TimeValue(NanoSeconds(delayNanoSeconds)));

    NodeContainer tapNodes;
    NetDeviceContainer tapDevices;
    NodeContainer internetStackNodes;

    tapNodes.Add(nodes.Get(0));
    NodeContainer firstLink = NodeContainer(nodes.Get(0), nodes.Get(1));
    NetDeviceContainer firstDevices = csma.Install(firstLink);
    tapDevices.Add(firstDevices.Get(0));

    InternetStackHelper stack;
    for (uint16_t router = 1; router < (noOfRouters + 1); router++) {
        stack.Install(nodes.Get(router));
    }
    Ipv4AddressHelper addresses;
    addresses.SetBase("172.20.0.0", "255.255.255.0");
    Ipv4InterfaceContainer ignored = addresses.Assign(firstDevices.Get(1));

    for (uint16_t router = 1; router < noOfRouters; router++) {
        NodeContainer link = NodeContainer(nodes.Get(router), nodes.Get(router + 1));
        NetDeviceContainer linkDevices = csma.Install(link);

        addresses.SetBase(("172.20." + std::to_string(router) + ".0").c_str(), "255.255.255.0");
        ignored = addresses.Assign(linkDevices);
    }

    tapNodes.Add(nodes.Get(noOfRouters + 1));
    NodeContainer lastLink = NodeContainer(nodes.Get(noOfRouters), nodes.Get(noOfRouters + 1));
    NetDeviceContainer lastDevices = csma.Install(lastLink);
    tapDevices.Add(lastDevices.Get(1));
    internetStackNodes.Add(nodes.Get(noOfRouters));

    addresses.SetBase(("172.20." + std::to_string(noOfRouters) + ".0").c_str(), "255.255.255.0");
    ignored = addresses.Assign(lastDevices.Get(0));

    TapBridgeHelper tapBridge;
    tapBridge.SetAttribute("Mode", StringValue(mode));
    tapBridge.SetAttribute("DeviceName", StringValue(tapName0));
    tapBridge.Install(tapNodes.Get(0), tapDevices.Get(0));

    tapBridge.SetAttribute("DeviceName", StringValue(tapName1));
    tapBridge.Install(tapNodes.Get(1), tapDevices.Get(1));
    

    if (noOfRouters != 0) {
        Ipv4GlobalRoutingHelper::PopulateRoutingTables();
    }

    Simulator::Stop(Seconds(runSeconds));
    Simulator::Run();
    Simulator::Destroy();

    return 0;
}
