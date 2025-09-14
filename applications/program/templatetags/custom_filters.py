from django import template
register = template.Library()


@register.filter
def non_stage(programs):
    return programs.filter(non_stage=True)


@register.filter
def stage(programs):
    return programs.filter(non_stage=False)
