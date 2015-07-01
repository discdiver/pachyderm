// package container contains convenience functions for manipulating containers
package container

import (
	"errors"
	"io"
	"os"
	"path/filepath"
	"strings"

	"github.com/fsouza/go-dockerclient"
)

const defaultDockerHost = "unix:///var/run/docker.sock"

var DefaultConfig = docker.Config{
	AttachStdin:  true,
	AttachStdout: true,
	AttachStderr: true,
	OpenStdin:    true,
	StdinOnce:    true,
}

func RawStartContainer(opts docker.CreateContainerOptions) (string, error) {
	client, err := NewDockerClientFromEnv()
	if err != nil {
		return "", err
	}
	container, err := client.CreateContainer(opts)
	if err != nil {
		return "", err
	}
	err = client.StartContainer(container.ID, opts.HostConfig)
	if err != nil {
		return "", err
	}

	return container.ID, nil
}

func StartContainer(image string, command []string) (string, error) {
	config := docker.Config{Image: image, Cmd: command}
	opts := docker.CreateContainerOptions{Config: &config}
	return RawStartContainer(opts)
}

func StopContainer(id string) error {
	client, err := NewDockerClientFromEnv()
	if err != nil {
		return err
	}
	return client.StopContainer(id, 5)
}

func KillContainer(id string) error {
	client, err := NewDockerClientFromEnv()
	if err != nil {
		return err
	}
	return client.KillContainer(docker.KillContainerOptions{ID: id})
}

func IpAddr(containerId string) (string, error) {
	client, err := NewDockerClientFromEnv()
	if err != nil {
		return "", err
	}
	container, err := client.InspectContainer(containerId)
	if err != nil {
		return "", err
	}

	return container.NetworkSettings.IPAddress, nil
}

func PullImage(image string) error {
	repo_tag := strings.Split(image, ":")
	client, err := NewDockerClientFromEnv()
	if err != nil {
		return err
	}
	opts := docker.PullImageOptions{Repository: repo_tag[0], Tag: "latest"}
	if len(repo_tag) == 2 {
		opts.Tag = repo_tag[1]
	}
	return client.PullImage(opts, docker.AuthConfiguration{})
}

func PipeToStdin(id string, in io.Reader) error {
	client, err := NewDockerClientFromEnv()
	if err != nil {
		return err
	}
	return client.AttachToContainer(docker.AttachToContainerOptions{
		Container:   id,
		InputStream: in,
		Stdin:       true,
		Stream:      true,
	})
}

func ContainerLogs(id string, out io.Writer) error {
	client, err := NewDockerClientFromEnv()
	if err != nil {
		return err
	}
	return client.AttachToContainer(docker.AttachToContainerOptions{
		Container:    id,
		OutputStream: out,
		ErrorStream:  out,
		Stdout:       true,
		Stderr:       true,
		Logs:         true,
	})
}

func WaitContainer(id string) (int, error) {
	client, err := NewDockerClientFromEnv()
	if err != nil {
		return 0, err
	}

	return client.WaitContainer(id)
}

func NewDockerClientFromEnv() (*docker.Client, error) {
	host := os.Getenv("DOCKER_HOST")

	if host == "" {
		host = defaultDockerHost
	}

	if os.Getenv("DOCKER_TLS_VERIFY") != "" {
		path := os.Getenv("DOCKER_CERT_PATH")

		if path == "" {
			path = os.Getenv("HOME")

			if path == "" {
				return nil, errors.New("pfs: environment variable HOME must be set if DOCKER_CERT_PATH is not set")
			}

			var err error

			path = filepath.Join(path, ".docker")
			path, err = filepath.Abs(path)

			if err != nil {
				return nil, err
			}
		}

		return docker.NewTLSClient(
			host,
			path+"/cert.pem",
			path+"/key.pem",
			path+"/ca.pem",
		)
	}

	return docker.NewClient(host)
}
