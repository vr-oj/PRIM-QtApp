
import imagingcontrol4 as ic4

def example_event_line1_edge():
    # Let the user select one of the connected cameras
    device_list = ic4.DeviceEnum.devices()
    for i, dev in enumerate(device_list):
        print(f"[{i}] {dev.model_name} ({dev.serial}) [{dev.interface.display_name}]")
    print(f"Select device [0..{len(device_list) - 1}]: ", end="")
    selected_index = int(input())
    dev_info = device_list[selected_index]

    # Open the selected device in a new Grabber
    grabber = ic4.Grabber(dev_info)
    map = grabber.device_property_map

    # GigEVision and USB3Vision devices can send asynchronous events to applications
    # This example shows how to receive events EventLine1RisingEdge and EventLine1FallingEdge, which indicate activity
    # on one of the camera's digital inputs.
    #
    # Events are configured and received through the device property map.
    # The following shows an excerpt from the device property map of a device supporting EventLine1RisingEdge and EventLine1FallingEdge:
    #
    # - EventControl
    #   - EventSelector
    #   - EventNotification[EventSelector]
    #   - EventLine1RisingEdgeData
    #     - EventLine1RisingEdge
    #     - EventLine1RisingEdgeTimestamp
    #   - EventLine1FallingEdgeData
    #     - EventLine1FallingEdge
    #     - EventLine1FallingEdgeTimestamp
    #
    # To receive notifications for a specific event, two steps have to be taken:
    #
    # First, the device has to be configured to send generate the specific event. To enable the EventLine1RisingEdge event, set the
    # "EventSelector" enumeration property to "EventLine1RisingEdge", and then set the "EventNotification" enumeration property to "On".
    #
    # Second, a property notification handler has to be registered for the property representing the event.
    # The EventLine1RisingEdge is represented by the integer property "EventLine1RisingEdge". This property has no function other
    # than being invalidated and thus having its notification raised when the device sends the event.
    #
    # Event parameters are grouped with the event property in a property category with "Data" appended to the event's name,
    # in our case "EventLine1RisingEdgeData". The category contains the integer property "EventLine1RisingEdgeTimestamp"
    # which provides the time stamp of the event. Event argument properties should only be read inside the event notification
    # function to avoid data races.

    # Get Line1RisingEdge and Line1FallingEdge event properties
    event_line1_rising_edge = map.find(ic4.PropId.EVENT_LINE1_RISING_EDGE)
    event_line1_falling_edge = map.find(ic4.PropId.EVENT_LINE1_FALLING_EDGE)
    # Get Line1RisingEdge and Line1FallingEdge timestamp arguments
    event_line1_rising_edge_timestamp = map.find(ic4.PropId.EVENT_LINE1_RISING_EDGE_TIMESTAMP)
    event_line1_falling_edge_timestamp = map.find(ic4.PropId.EVENT_LINE1_FALLING_EDGE_TIMESTAMP)

    # Enable both Line1RisingEdge and Line1FallingEdge event notifications
    map.set_value(ic4.PropId.EVENT_SELECTOR, "Line1RisingEdge")
    map.set_value(ic4.PropId.EVENT_NOTIFICATION, "On")
    map.set_value(ic4.PropId.EVENT_SELECTOR, "Line1FallingEdge")
    map.set_value(ic4.PropId.EVENT_NOTIFICATION, "On")

    # Register notification handler for Line1RisingEdge
    def on_rising_edge(prop: ic4.Property):
        print(f"Line1 Rising Edge\t(Timestamp = {event_line1_rising_edge_timestamp.value})")
    rising_edge_token = event_line1_rising_edge.event_add_notification(on_rising_edge)

    # Register notification handler for Line1FallingEdge
    def on_falling_edge(prop: ic4.Property):
        print(f"Line1 Falling Edge\t(Timestamp = {event_line1_falling_edge_timestamp.value})")
    falling_edge_token = event_line1_falling_edge.event_add_notification(on_falling_edge)

    input("Waiting for Line1RisingEdge and Line1FallingEdge events. Press ENTER to exit")

    # Unregister event notifications (for completeness only, we close the device anyway)
    event_line1_rising_edge.event_remove_notification(rising_edge_token)
    event_line1_falling_edge.event_remove_notification(falling_edge_token)

    # Disable event notifications
    map.set_value(ic4.PropId.EVENT_SELECTOR, "Line1RisingEdge")
    map.set_value(ic4.PropId.EVENT_NOTIFICATION, "Off")
    map.set_value(ic4.PropId.EVENT_SELECTOR, "Line1FallingEdge")
    map.set_value(ic4.PropId.EVENT_NOTIFICATION, "Off")

    # Only for completeness. Technically this is not necessary here, since the grabber is destroyed at the end of the function.
    grabber.device_close()

if __name__ == "__main__":
    with ic4.Library.init_context(api_log_level=ic4.LogLevel.INFO, log_targets=ic4.LogTarget.STDERR):

        example_event_line1_edge()