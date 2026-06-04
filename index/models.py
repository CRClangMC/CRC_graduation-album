from django.db import models


class Pic(models.Model):
    id = models.CharField(max_length=50, primary_key=True)
    vector = models.TextField()
    path = models.CharField(max_length=255)
    creater = models.CharField(max_length=150)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'pic'
        managed = False

    def __str__(self):
        return self.path


class Vdo(models.Model):
    id = models.CharField(max_length=50, primary_key=True)
    file_name = models.CharField(max_length=255)
    path = models.CharField(max_length=255)
    creater = models.CharField(max_length=150)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'vdo'
        managed = False

    def __str__(self):
        return self.file_name
