from django import forms


class ContainerForm(forms.Form):
    name = forms.CharField(label="Container Name", required=True)
    memory = forms.CharField(label="Memory Limit (e.g., 512m, 1g)", required=False)
    memory_swap = forms.CharField(
        label="Memory Swap (e.g., 1g, -1 for unlimited)", required=False
    )
    cpu_share = forms.IntegerField(label="CPU Shares (relative weight)", required=False)
    user = forms.CharField(label="User (format: <uid>:<gid>)", required=False)
    image_name = forms.CharField(label="Image Name", initial="ubuntu")
