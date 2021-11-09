#ifndef PYVAC248IPNATIVE_LIBRARY_H
#define PYVAC248IPNATIVE_LIBRARY_H

#include <stdint.h>


#define PYVAC248IPNATIVE_VERSION_MAJOR 1
#define PYVAC248IPNATIVE_VERSION_MINOR 0
#define PYVAC248IPNATIVE_VERSION_BUGFIX 0


#ifdef __GNUC__
#   define PYVAC248IPNATIVE_API \
        __attribute__((visibility("default"))) __attribute__((used))
#else
#   define PYVAC248IPNATIVE_API
#endif


PYVAC248IPNATIVE_API
int
pyvac248ipnative_get_version(
        int *major,
        int *minor,
        int *bugfix
);


PYVAC248IPNATIVE_API
int
pyvac248ipnative_capture_packets(
        void *dst,
        int dst_size,
        int *packets_received,

        int socket_fd,
        int frames,
        int frame_packets,
        uint32_t camera_ip,
        uint16_t camera_port,
        int video_format,
        int max_incorrect_length_packets,

        int send_command_delay_ms,
        int get_frame_delay_ms,
        int drop_packets_delay_ms,
        int network_operation_timeout_ms,

        uint8_t exposure
);


#endif  // PYVAC248IPNATIVE_LIBRARY_H
