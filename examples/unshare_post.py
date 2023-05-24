from atproto import AtUri, Client


def main():
    client = Client()
    client.login('my-handle', 'my-password')

    # same with the like_post.py example we need to keep a reference to the post
    post_ref = client.send_post('Test like-unlike from Python SDK')
    print('Post reference:', post_ref)

    # rkey means record key. The ID of the post object
    post_rkey = AtUri.from_str(post_ref.uri).rkey
    print('Post rkey:', post_rkey)

    # this methods return True/False depends on the response. Could throw exceptions too
    print(client.unshare(post_rkey))


if __name__ == '__main__':
    main()