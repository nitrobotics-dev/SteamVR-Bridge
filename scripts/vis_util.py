import numpy as np
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
from mpl_toolkits.mplot3d import Axes3D  # noqa

fig = plt.figure()
ax = fig.add_subplot(111, projection='3d')

# Fixed world axis limits
ax.set_xlim(-1, 1)
ax.set_ylim(-1, 1)
ax.set_zlim(-1, 1)

# Initialize 3 colored axes as line objects
x_line, = ax.plot([], [], [], 'r-')  # x-axis
y_line, = ax.plot([], [], [], 'g-')  # y-axis
z_line, = ax.plot([], [], [], 'b-')  # z-axis


def pose_stream():
    """Generator yielding 4x4 pose matrices in real time."""
    t = 0.0
    while True:
        # Example: rotating around z and translating in x
        c, s = np.cos(t), np.sin(t)
        T = np.array([
            [c, -s, 0, 0.5 * c],
            [s,  c, 0, 0.5 * s],
            [0,  0, 1, 0.0],
            [0,  0, 0, 1.0],
        ])
        yield T
        t += 0.05


poses = pose_stream()


def update(frame):
    T = next(poses)  # your 4x4 pose matrix here

    R = T[:3, :3]
    p = T[:3, 3]

    # Local frame unit axes in homogeneous coords
    origin = p
    x_axis = origin + R @ np.array([1, 0, 0])
    y_axis = origin + R @ np.array([0, 1, 0])
    z_axis = origin + R @ np.array([0, 0, 1])

    # Update line data
    x_line.set_data([origin[0], x_axis[0]], [origin[1], x_axis[1]])
    x_line.set_3d_properties([origin[2], x_axis[2]])

    y_line.set_data([origin[0], y_axis[0]], [origin[1], y_axis[1]])
    y_line.set_3d_properties([origin[2], y_axis[2]])

    z_line.set_data([origin[0], z_axis[0]], [origin[1], z_axis[1]])
    z_line.set_3d_properties([origin[2], z_axis[2]])

    return x_line, y_line, z_line


ani = FuncAnimation(fig, update, interval=30, blit=False)
plt.show()
