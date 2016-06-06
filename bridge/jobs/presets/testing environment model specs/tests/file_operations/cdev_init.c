#include <linux/module.h>
#include <linux/fs.h>
#include <linux/cdev.h>
#include <linux/emg/test_model.h>
#include <verifier/nondet.h>

int flip_a_coin;

static int ldv_open(struct inode *inode, struct file *filp)
{
	ldv_invoke_callback();
    return 0;
}

static int ldv_release(struct inode *inode, struct file *filp)
{
	ldv_invoke_callback();
    return 0;
}

static struct cdev ldv_cdev;

static struct file_operations ldv_fops = {
	.open		= ldv_open,
	.release	= ldv_release,
	.owner		= THIS_MODULE,
};

static int __init ldv_init(void)
{
	flip_a_coin = ldv_undef_int();
    if (flip_a_coin) {
        ldv_register();
        cdev_init(&ldv_cdev, &ldv_fops);
    }
    return 0;
}

static void __exit ldv_exit(void)
{
	if (flip_a_coin) {
        cdev_del(&ldv_cdev);
        ldv_deregister();
    }
}

module_init(ldv_init);
module_exit(ldv_exit);
