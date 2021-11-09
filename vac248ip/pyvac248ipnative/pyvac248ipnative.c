#include "pyvac248ipnative.h"

#include <stddef.h>
#include <string.h>
#include <time.h>
#include <errno.h>

#include <poll.h>
#include <fcntl.h>
#include <sys/types.h>
#include <sys/socket.h>
#include <netinet/ip.h>
#include <arpa/inet.h>


#define PYVAC248IPNATIVE_IMPL_DATA_PACKET_SIZE_ 1472
#define PYVAC248IPNATIVE_IMPL_CONFIG_PACKET_SIZE_ 48


#define pyvac248ipnative_impl_send_command_start_(socket_fd, camera_ip, camera_port, format, send_command_delay_ms) \
    pyvac248ipnative_impl_send_command_(socket_fd, camera_ip, camera_port, 0x5a, (format) | 0x80, send_command_delay_ms)


#define pyvac248ipnative_impl_send_command_stop_(socket_fd, camera_ip, camera_port, send_command_delay_ms) \
    pyvac248ipnative_impl_send_command_(socket_fd, camera_ip, camera_port, 0x5a, 0x00, send_command_delay_ms)


#define pyvac248ipnative_impl_send_command_exposure_(socket_fd, camera_ip, camera_port, exposure, send_command_delay_ms) \
    pyvac248ipnative_impl_send_command_(socket_fd, camera_ip, camera_port, 0xc0, exposure, send_command_delay_ms)


static
int
pyvac248ipnative_impl_send_command_(
        int socket_fd,
        uint32_t camera_ip,
        uint16_t camera_port,
        unsigned int command,
        unsigned int data,
        int send_command_delay_ms
);


static
int
pyvac248ipnative_impl_drop_packets_(
        int socket_fd,
        int drop_packets_delay_ms
);


static
int
pyvac248ipnative_impl_set_socket_timeout_(
        int socket_fd,
        int timeout_ms
);


static
int
pyvac248ipnative_impl_sleep_ms_(
        int delay_ms
);


PYVAC248IPNATIVE_API
int
pyvac248ipnative_get_version(
        int *major,
        int *minor,
        int *bugfix
)
{
    if (major != NULL) {
        *major = PYVAC248IPNATIVE_VERSION_MAJOR;
    }

    if (minor != NULL) {
        *minor = PYVAC248IPNATIVE_VERSION_MINOR;
    }

    if (bugfix != NULL) {
        *bugfix = PYVAC248IPNATIVE_VERSION_BUGFIX;
    }

    return 0;
}


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
)
{
    int
        packets_received_ = 0,
        incorrect_packets_length = 0;

    unsigned char * const dst_casted = (unsigned char *)dst;
    unsigned char *packet_buffer;
    int packet_buffer_offset;

    int frame_number;
    int packet_offset;

    struct pollfd poll_fd = { .fd = socket_fd, .events = POLLIN | POLLERR, .revents = 0 };
    int poll_res;

    struct sockaddr_in src_sockaddr;
    socklen_t src_sockaddr_len;
    ssize_t recvfrom_res;

    int fcntl_res_before, fcntl_res_required;

    int result = 0;
    int errno_ = 0;

    // Set socket non-blocking mode
    fcntl_res_before = fcntl(socket_fd, F_GETFL, 0);
    if (fcntl_res_before < 0) {
        return -1;
    }
    fcntl_res_required = fcntl_res_before | O_NONBLOCK;
    if (fcntl_res_required != fcntl_res_before) {
        if (fcntl(socket_fd, F_SETFL, fcntl_res_required) < 0) {
            return -1;
        }
    }

    // Set default packet type to 0 (data packet)
    for (unsigned char *p = dst_casted; p < dst_casted + dst_size; p += PYVAC248IPNATIVE_IMPL_DATA_PACKET_SIZE_ + 1) {
        *p = 0;
    }

    // Start video stream
    pyvac248ipnative_impl_send_command_stop_(socket_fd, camera_ip, camera_port, send_command_delay_ms);
    pyvac248ipnative_impl_drop_packets_(socket_fd, drop_packets_delay_ms);
    pyvac248ipnative_impl_send_command_start_(socket_fd, camera_ip, camera_port, video_format, send_command_delay_ms);

    /*
     * It is important to set expositions right here after start() command.
     * This affects for the image brightness.
     * If you will not set exposition here (and set it somewhere else),
     * the brightness will be different from the Vasily’s software.
     * See #41292 for more details
     */
    pyvac248ipnative_impl_send_command_exposure_(socket_fd, camera_ip, camera_port, exposure, send_command_delay_ms);

    while (packets_received_ < dst_size) {
        packet_buffer_offset = packets_received_ * (PYVAC248IPNATIVE_IMPL_DATA_PACKET_SIZE_ + 1);
        packet_buffer = dst_casted + packet_buffer_offset + 1;

        poll_fd.revents = 0;
        poll_res = poll(&poll_fd, 1, network_operation_timeout_ms);
        if (poll_res == 1) {
            // Do nothing, packet ready
        } else if (poll_res == 0) {
            // Timeout
            result = 1;
            break;
        } else {
            // Any error occurred, see errno
            result = -1;
            errno_ = errno;
            break;
        }

        recvfrom_res = recvfrom(
                socket_fd,
                packet_buffer, PYVAC248IPNATIVE_IMPL_DATA_PACKET_SIZE_, 0,
                (struct sockaddr *)&src_sockaddr, &src_sockaddr_len
        );

        if (recvfrom_res < 0) {
            // Any error occurred, see errno
            result = -1;
            errno_ = errno;
            break;
        }

        if (recvfrom_res == PYVAC248IPNATIVE_IMPL_DATA_PACKET_SIZE_) {
            // Check camera ip
            if (src_sockaddr.sin_addr.s_addr != camera_ip) {
                continue;
            }

            // Data packet received
            // [frame number (bytes: 0) | pix number (bytes: 1 hi, 2, 3 low) | pixel data (bytes: [4...1472))]

            incorrect_packets_length = 0;

            frame_number = packet_buffer[0];
            packet_offset = (((int)packet_buffer[1]) << 16) | (((int)packet_buffer[2]) << 8) | (int)packet_buffer[3];

            if (
                    frame_number == 0 ||
                    packet_offset > (PYVAC248IPNATIVE_IMPL_DATA_PACKET_SIZE_ - 4) * (frame_packets - 1) ||
                    packet_offset % (PYVAC248IPNATIVE_IMPL_DATA_PACKET_SIZE_ - 4) != 0
            ) {
                // Skip the first frame, which can be overexposed
                // Filter incorrect offsets (assuming c-version is fast enough to do simple additional filtering online)
                continue;
            } else if (frame_number > frames) {
                // All required frames received, stop packets collecting algorithm
                result = 0;
                break;
            }
        } else if (recvfrom_res == PYVAC248IPNATIVE_IMPL_CONFIG_PACKET_SIZE_) {
            // Check camera ip
            if (src_sockaddr.sin_addr.s_addr != camera_ip) {
                continue;
            }

            // Config packet received
            dst_casted[packet_buffer_offset] = 1;
            incorrect_packets_length = 0;
        } else {
            ++incorrect_packets_length;
            if (incorrect_packets_length > max_incorrect_length_packets) {
                result = 2;
                break;
            } else {
                continue;
            }
        }

        ++packets_received_;
    }

    // Stop video translation
    pyvac248ipnative_impl_send_command_stop_(socket_fd, camera_ip, camera_port, send_command_delay_ms);
    pyvac248ipnative_impl_sleep_ms_(get_frame_delay_ms);
    pyvac248ipnative_impl_drop_packets_(socket_fd, drop_packets_delay_ms);

    // Restore socket blocking mode and timeout
    if (
            fcntl_res_required != fcntl_res_before && (
                fcntl(socket_fd, F_SETFL, fcntl_res_before) < 0 ||
                pyvac248ipnative_impl_set_socket_timeout_(socket_fd, network_operation_timeout_ms) < 0
            )
    ) {
        if (errno_ == 0) {
            errno_ = errno;
        }
        result = -1;
    }

    // Set output data
    if (result == -1) {
        errno = errno_;
        packets_received_ = 0;
    }
    *packets_received = packets_received_;

    return result;
}


static
int
pyvac248ipnative_impl_send_command_(
        int socket_fd,
        uint32_t camera_ip,
        uint16_t camera_port,
        unsigned int command,
        unsigned int data,
        int send_command_delay_ms
)
{
    const unsigned char buf[] = {
            (unsigned char)(command & 0xff),
            (unsigned char)(data & 0xff),
            0x00,
            0x00,
            0x00,
            0x00,
            0x00,
            (unsigned char)((command + data) & 0xff)  // Checksum
    };
    struct sockaddr_in dst_sockaddr;

    memset(&dst_sockaddr, 0, sizeof(dst_sockaddr));
    dst_sockaddr.sin_family = AF_INET;
    dst_sockaddr.sin_port = htons(camera_port);
    dst_sockaddr.sin_addr.s_addr = camera_ip;

    if (sendto(socket_fd, buf, sizeof(buf), 0, (struct sockaddr *)&dst_sockaddr, sizeof(dst_sockaddr)) < 0) {
        return -1;
    }

    return pyvac248ipnative_impl_sleep_ms_(send_command_delay_ms);
}


static
int
pyvac248ipnative_impl_drop_packets_(
        int socket_fd,
        int drop_packets_delay_ms
)
{
    unsigned char buf[PYVAC248IPNATIVE_IMPL_DATA_PACKET_SIZE_];

    pyvac248ipnative_impl_sleep_ms_(drop_packets_delay_ms);

    while (recvfrom(socket_fd, buf, sizeof(buf), 0, NULL, 0) >= 0) {
        // Just receive packets and forget about them
    }

    return (errno == EAGAIN || errno == EWOULDBLOCK)? 0: -1;
}


static
int
pyvac248ipnative_impl_set_socket_timeout_(
        int socket_fd,
        int timeout_ms
)
{
    struct timeval timeout;
    timeout.tv_sec = timeout_ms / 1000;
    timeout.tv_usec = (timeout_ms % 1000) * 1000;

    if (
            setsockopt(socket_fd, SOL_SOCKET, SO_RCVTIMEO, (void *)&timeout, sizeof(timeout)) < 0 ||
            setsockopt(socket_fd, SOL_SOCKET, SO_SNDTIMEO, (void *)&timeout, sizeof(timeout)) < 0
    ) {
        return -1;
    }

    return 0;
}


static
int
pyvac248ipnative_impl_sleep_ms_(
        int delay_ms
)
{
    struct timespec req, rem;
    int nanosleep_res;
    int result = 0;

    req.tv_sec = delay_ms / 1000;
    req.tv_nsec = (delay_ms % 1000) * 1000000;

    while (1) {
        nanosleep_res = nanosleep(&req, &rem);
        if (nanosleep_res == 0) {
            break;
        } else if (errno == EINTR) {
            req = rem;
        } else {
            result = -1;
            break;
        }
    }

    return result;
}
