-- A finding the lawyer adds by hand doesn't belong to a pipeline layer
alter table findings alter column layer drop not null;
alter table findings add constraint findings_layer_required
  check (layer is not null or advocate_action = 'add');
