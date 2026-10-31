from django.db import migrations, models


def keep_existing_accounts_working(apps, schema_editor):
    # accounts created before email confirmation existed stay as they are
    apps.get_model("accounts", "Profile").objects.update(email_verified=True)


class Migration(migrations.Migration):
    dependencies = [("accounts", "0001_initial")]

    operations = [
        migrations.AddField(model_name="profile", name="email_verified", field=models.BooleanField(default=False)),
        migrations.RunPython(keep_existing_accounts_working, migrations.RunPython.noop),
    ]
